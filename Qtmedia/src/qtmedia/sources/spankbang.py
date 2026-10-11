"""CLI-only SpankBang access options."""

from __future__ import annotations

import os
from urllib.parse import urlparse

SPANKBANG_HOST = "spankbang.com"
# Mirror domains serving the same video IDs and paths as spankbang.com.
# yt-dlp's SpankBang extractor only matches spankbang.com, so mirror links are
# rewritten to the canonical host before extraction.
SPANKBANG_MIRROR_HOSTS = frozenset({"spankbang.party"})
SUPPORTED_COOKIE_BROWSERS = frozenset({"firefox"})


def _matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def is_spankbang_url(url: str) -> bool:
    """Return whether a URL belongs to SpankBang, a mirror, or a subdomain."""

    host = (urlparse(url).hostname or "").casefold().rstrip(".")
    return any(_matches(host, domain) for domain in {SPANKBANG_HOST, *SPANKBANG_MIRROR_HOSTS})


def canonical_spankbang_url(url: str) -> str:
    """Rewrite a SpankBang mirror URL to spankbang.com; return others unchanged."""

    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold().rstrip(".")
    mirror = next((domain for domain in SPANKBANG_MIRROR_HOSTS if _matches(host, domain)), None)
    if mirror is None or parsed.username is not None or parsed.password is not None:
        return url
    canonical = host[: -len(mirror)] + SPANKBANG_HOST
    netloc = canonical if parsed.port is None else f"{canonical}:{parsed.port}"
    return parsed._replace(netloc=netloc).geturl()


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
