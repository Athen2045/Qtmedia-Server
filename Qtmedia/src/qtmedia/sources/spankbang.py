"""CLI-only SpankBang access options."""

from __future__ import annotations

import os
from urllib.parse import urlparse

SPANKBANG_HOST = "spankbang.com"
SUPPORTED_COOKIE_BROWSERS = frozenset({"firefox"})


def is_spankbang_url(url: str) -> bool:
    """Return whether a URL belongs to SpankBang or one of its subdomains."""

    host = (urlparse(url).hostname or "").casefold().rstrip(".")
    return host == SPANKBANG_HOST or host.endswith(f".{SPANKBANG_HOST}")


def _configured_cookie_browser() -> str | None:
    browser = os.getenv("PRIVATE_SEARCH_CLI_YTDLP_COOKIES_FROM_BROWSER", "").strip().casefold()
    if not browser:
        return None
    if browser not in SUPPORTED_COOKIE_BROWSERS:
        raise ValueError(
            "PRIVATE_SEARCH_CLI_YTDLP_COOKIES_FROM_BROWSER must be firefox"
        )
    return browser


def spankbang_ydl_options(url: str) -> dict[str, object]:
    """Return ephemeral, opt-in browser-cookie options for SpankBang only."""

    if not is_spankbang_url(url):
        return {}
    browser = _configured_cookie_browser()
    if browser is None:
        return {}
    profile = os.getenv("PRIVATE_SEARCH_CLI_YTDLP_COOKIES_BROWSER_PROFILE", "").strip() or None
    options: dict[str, object] = {
        "cookiesfrombrowser": (browser, profile, None, None),
        "cachedir": False,
    }
    user_agent = os.getenv("PRIVATE_SEARCH_CLI_YTDLP_USER_AGENT", "").strip()
    if not user_agent:
        raise ValueError(
            "PRIVATE_SEARCH_CLI_YTDLP_USER_AGENT is required with SpankBang cookie mode"
        )
    options["http_headers"] = {"User-Agent": user_agent}
    return options
