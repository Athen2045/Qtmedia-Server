"""Shared HTTP client for site-adapter scraping.

Plain ``requests`` has a TLS/HTTP fingerprint that several video sites block
outright — a 403, or a connection reset before any HTTP response is even
seen. When the optional ``curl_cffi`` dependency is installed (the same
dependency yt-dlp's extractor impersonation already uses, see
``ydl_options()``), route scraping requests through it so they present a
real browser's TLS fingerprint instead. Falls back to plain ``requests``
when curl_cffi isn't installed.
"""

from __future__ import annotations

import importlib.util
import os
import random
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import requests

HAS_CURL_CFFI = importlib.util.find_spec("curl_cffi") is not None

# Which browser fingerprint to present. Site-side bot detection changes over
# time, so this can be overridden without a code change if a target starts
# blocking the default.
IMPERSONATE_TARGET = os.getenv("PRIVATE_SEARCH_IMPERSONATE", "chrome131")

# yt-dlp names impersonation targets "client-version" (and resolves a bare
# client name to whichever version it has available), while curl_cffi uses a
# single run-together token. Only the profiles this project actually configures
# need an exact mapping; anything else degrades to the bare client name, which
# still gets a real browser fingerprint rather than yt-dlp's default one.
YTDLP_IMPERSONATE_TARGETS = {
    "chrome131": "chrome-131",
    "safari184": "safari-18.4",
}


def ytdlp_impersonate_target(profile: str | None = None) -> str | None:
    """Translate a curl_cffi profile name into a yt-dlp impersonate target.

    Returns None when curl_cffi is missing, since yt-dlp's impersonation is
    built on the same dependency and the option would only error without it.
    """
    if not HAS_CURL_CFFI:
        return None
    profile = profile or IMPERSONATE_TARGET
    if profile in YTDLP_IMPERSONATE_TARGETS:
        return YTDLP_IMPERSONATE_TARGETS[profile]
    client = re.match(r"[a-z]+", profile)
    return client.group(0) if client else None


RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.5
# Backoff is jittered because the retryable failures below are usually
# site-wide, not per-request: without jitter every worker that hit the same
# failing site wakes on the same 1.5s/3.0s schedule and re-fires as one burst,
# which is exactly the synchronised traffic pattern worth avoiding.
RETRY_JITTER_SECONDS = 0.5
MAX_RETRY_AFTER_SECONDS = 60.0

# Search pages are read in bounded chunks rather than as one whole-body copy,
# so a slow or oversized response is absorbed incrementally instead of forcing
# a single large buffer allocation. MAX_RESPONSE_BYTES is a backstop against a
# misrouted URL streaming something enormous into memory: real search result
# pages are well under a megabyte.
STREAM_CHUNK_BYTES = 8192
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
# Retried in addition to transport-level failures: some sites' search
# backends intermittently error on an otherwise-valid request rather than
# resetting the connection, so a 5xx/429 never reaches the except clause
# below on its own.
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

class ResponseTooLarge(Exception):
    """A response body exceeded MAX_RESPONSE_BYTES and was abandoned unread."""


if HAS_CURL_CFFI:
    from curl_cffi.requests import Session as _CurlSession
    from curl_cffi.requests.exceptions import RequestException as _CurlRequestException

    HTTP_EXCEPTIONS: tuple[type[Exception], ...] = (
        requests.RequestException,
        _CurlRequestException,
        ResponseTooLarge,
    )
else:
    HTTP_EXCEPTIONS = (requests.RequestException, ResponseTooLarge)


def new_session(impersonate: str | None = None):
    """Return a session presenting a real browser's TLS fingerprint when possible.

    Bot detection is inconsistent across sites: one site's Cloudflare rules
    challenge a Chrome fingerprint but pass a Safari one, another does the
    opposite. ``impersonate`` lets a call site override the default target;
    pass None to use ``IMPERSONATE_TARGET``.
    """
    if HAS_CURL_CFFI:
        return _CurlSession(impersonate=impersonate or IMPERSONATE_TARGET)
    return requests.Session()


def request_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Headers to layer on top of a session.

    curl_cffi's impersonation already sets a User-Agent (and other headers)
    consistent with the TLS fingerprint it presents; overriding it with a
    generic string would make the request inconsistent and easier to flag.
    Plain ``requests`` has no such profile, so it needs an explicit one.
    """
    headers = dict(extra or {})
    if not HAS_CURL_CFFI:
        headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        )
    return headers


def _retry_after_seconds(response) -> float | None:
    """Return a bounded Retry-After delay when a server supplied one."""

    headers = getattr(response, "headers", None)
    if not headers:
        return None
    raw = headers.get("Retry-After")
    if not raw:
        return None
    value = str(raw).strip()
    try:
        return max(0.0, min(float(value), MAX_RETRY_AFTER_SECONDS))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            return max(
                0.0,
                min(
                    (retry_at - datetime.now(UTC)).total_seconds(),
                    MAX_RETRY_AFTER_SECONDS,
                ),
            )
        except (TypeError, ValueError, OverflowError):
            return None


def get(session, url: str, **kwargs):
    """GET with a few retries.

    Several sites intermittently reset the connection, or return a 5xx/429
    on an otherwise-valid, browser-impersonated request, so a single attempt
    is not reliable enough to treat as a real failure. A non-retryable
    response (2xx, or a 4xx that isn't 429) is returned on the first try;
    once retries are exhausted the last response or error is returned/raised
    so the caller's own error handling (e.g. ``raise_for_status``) applies.
    """
    last_error: Exception | None = None
    response = None
    for attempt in range(RETRY_ATTEMPTS):
        if response is not None:
            # A superseded attempt's body is never read. Under stream=True that
            # body is still queued on the socket, so close it explicitly rather
            # than leaving it to garbage collection.
            response.close()
            response = None
        try:
            response = session.get(url, **kwargs)
        except HTTP_EXCEPTIONS as error:
            last_error = error
            response = None
        else:
            if response.status_code not in RETRYABLE_STATUS_CODES:
                return response
            last_error = None
        if attempt < RETRY_ATTEMPTS - 1:
            retry_after = _retry_after_seconds(response)
            backoff = RETRY_BACKOFF_SECONDS * (2**attempt)
            if retry_after is not None:
                backoff = max(backoff, retry_after)
            time.sleep(backoff + random.uniform(0, RETRY_JITTER_SECONDS))
    if response is not None:
        return response
    assert last_error is not None
    raise last_error


def read_text(response, max_bytes: int = MAX_RESPONSE_BYTES) -> str:
    """Read a streamed response body in bounded chunks and decode it.

    The whole-body ``response.text`` accessor asks for the entire payload in
    one go; reading STREAM_CHUNK_BYTES at a time keeps each copy small and
    lets the connection close as soon as the body is consumed. Requires the
    response to have been fetched with ``stream=True`` — on a non-streamed
    response this still works, it just iterates over an already-buffered body.

    Raises ResponseTooLarge once max_bytes is exceeded; the partial body is
    discarded rather than returned, since a truncated page parses into
    plausible-looking but incomplete results.
    """
    chunks: list[bytes] = []
    total = 0
    try:
        for chunk in response.iter_content(chunk_size=STREAM_CHUNK_BYTES):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                raise ResponseTooLarge(
                    f"response body exceeded {max_bytes} bytes: {response.url}"
                )
            chunks.append(chunk)
    finally:
        response.close()
    return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
