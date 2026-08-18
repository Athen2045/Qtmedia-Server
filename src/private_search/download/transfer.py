"""Shared, conservative yt-dlp transfer settings."""

from __future__ import annotations

import os
import re
import shutil

from ..net import http_client

REQUEST_TIMEOUT = 20
DEFAULT_DOWNLOAD_TIMEOUT = 60
MAX_DOWNLOAD_TIMEOUT = 600
DEFAULT_DOWNLOAD_RETRIES = 5
MAX_DOWNLOAD_RETRIES = 10
RETRY_SLEEP_SECONDS = 2.0
MAX_RETRY_SLEEP_SECONDS = 30.0
DEFAULT_CONCURRENT_FRAGMENTS = 4
MAX_CONCURRENT_FRAGMENTS = 8
SIZE_PATTERN = re.compile(r"^(?P<value>\d+)\s*(?P<unit>[kmg])?b?$", re.IGNORECASE)


def _yt_dlp_runtime_options() -> dict[str, object]:
    """Select an installed JavaScript runtime for YouTube challenge solving."""
    configured_name = os.getenv("PRIVATE_SEARCH_YTDLP_JS_RUNTIME", "").strip().casefold()
    configured_path = os.getenv("PRIVATE_SEARCH_YTDLP_JS_RUNTIME_PATH", "").strip()
    if configured_name in {"none", "off", "disabled"}:
        return {"js_runtimes": {}}

    candidates = (configured_name,) if configured_name else ("deno", "node", "bun", "quickjs")
    for name in candidates:
        if not name:
            continue
        runtime_path = configured_path or shutil.which(name)
        if runtime_path:
            return {"js_runtimes": {name: {"path": runtime_path}}}
    return {}


def _youtube_extractor_options() -> dict[str, object]:
    """Prefer a YouTube client that does not require android_vr PO tokens."""
    configured = os.getenv("PRIVATE_SEARCH_YOUTUBE_PLAYER_CLIENTS", "web_embedded")
    clients = [item.strip() for item in configured.split(",") if item.strip()]
    return {"youtube": {"player_client": clients}} if clients else {}


def _configured_int(name: str, default: int, maximum: int | None = None) -> int:
    value = os.getenv(name, "").strip()
    try:
        parsed = int(value)
    except ValueError:
        return default
    if parsed <= 0:
        return default
    return min(parsed, maximum) if maximum is not None else parsed


def _configured_size(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    match = SIZE_PATTERN.fullmatch(value)
    if not match:
        return None
    multiplier = {"k": 1024, "m": 1024**2, "g": 1024**3}
    return int(match.group("value")) * multiplier.get((match.group("unit") or "").casefold(), 1)


def _download_retry_sleep(n: int = 1) -> float:
    """Back off between transient HTTP/fragment retries without hanging forever."""

    return min(RETRY_SLEEP_SECONDS * max(1, n), MAX_RETRY_SLEEP_SECONDS)


def common_ydl_options(
    *,
    timeout: int = REQUEST_TIMEOUT,
    retries: int = http_client.RETRY_ATTEMPTS,
    retry_sleep: bool = False,
) -> dict[str, object]:
    """Return transfer settings shared by inspection and download paths."""
    options: dict[str, object] = {
        "retries": retries,
        "fragment_retries": retries,
        "socket_timeout": timeout,
        "continuedl": True,
        "concurrent_fragment_downloads": _configured_int(
            "PRIVATE_SEARCH_CONCURRENT_FRAGMENTS",
            DEFAULT_CONCURRENT_FRAGMENTS,
            MAX_CONCURRENT_FRAGMENTS,
        ),
        **_yt_dlp_runtime_options(),
        "extractor_args": _youtube_extractor_options(),
    }
    if retry_sleep:
        options["retry_sleep_functions"] = {
            "http": _download_retry_sleep,
            "fragment": _download_retry_sleep,
            "extractor": _download_retry_sleep,
        }
    http_chunk_size = _configured_size("PRIVATE_SEARCH_HTTP_CHUNK_SIZE")
    if http_chunk_size is not None:
        options["http_chunk_size"] = http_chunk_size
    return options


def download_ydl_options() -> dict[str, object]:
    """Return yt-dlp settings tuned for slow or intermittently failing CDNs."""

    return common_ydl_options(
        timeout=_configured_int(
            "PRIVATE_SEARCH_DOWNLOAD_TIMEOUT",
            DEFAULT_DOWNLOAD_TIMEOUT,
            MAX_DOWNLOAD_TIMEOUT,
        ),
        retries=_configured_int(
            "PRIVATE_SEARCH_DOWNLOAD_RETRIES",
            DEFAULT_DOWNLOAD_RETRIES,
            MAX_DOWNLOAD_RETRIES,
        ),
        retry_sleep=True,
    )
