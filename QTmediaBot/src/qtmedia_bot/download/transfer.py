"""Shared, conservative yt-dlp transfer settings."""

from __future__ import annotations

import os
import re
import shutil

from ..net import http_client

REQUEST_TIMEOUT = 20
DEFAULT_CONCURRENT_FRAGMENTS = 4
MAX_CONCURRENT_FRAGMENTS = 8
SIZE_PATTERN = re.compile(r"^(?P<value>\d+)\s*(?P<unit>[kmg])?b?$", re.IGNORECASE)
SUPPORTED_RUNTIMES = frozenset({"bun", "deno", "node", "quickjs"})
DISABLED_RUNTIME_VALUES = frozenset({"", "off", "none", "disabled"})


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


def javascript_runtime_options() -> dict[str, object]:
    """Enable one configured, locally installed yt-dlp JavaScript runtime."""

    configured = os.getenv("PRIVATE_SEARCH_YTDLP_JS_RUNTIME", "node").strip().casefold()
    if configured in DISABLED_RUNTIME_VALUES or configured not in SUPPORTED_RUNTIMES:
        return {}
    runtime_path = shutil.which(configured)
    if runtime_path is None:
        return {}
    return {"js_runtimes": {configured: {"path": runtime_path}}}


def common_ydl_options() -> dict[str, object]:
    """Return transfer settings shared by inspection and download paths."""
    options: dict[str, object] = {
        "retries": http_client.RETRY_ATTEMPTS,
        "fragment_retries": http_client.RETRY_ATTEMPTS,
        "socket_timeout": REQUEST_TIMEOUT,
        "continuedl": True,
        "concurrent_fragment_downloads": _configured_int(
            "PRIVATE_SEARCH_CONCURRENT_FRAGMENTS",
            DEFAULT_CONCURRENT_FRAGMENTS,
            MAX_CONCURRENT_FRAGMENTS,
        ),
    }
    http_chunk_size = _configured_size("PRIVATE_SEARCH_HTTP_CHUNK_SIZE")
    if http_chunk_size is not None:
        options["http_chunk_size"] = http_chunk_size
    if os.getenv("PRIVATE_SEARCH_YTDLP_FORCE_IPV4", "0").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        # yt-dlp's Python API uses source_address for the CLI's -4 behavior.
        options["source_address"] = "0.0.0.0"
    return options
