"""yt-dlp options owned by the Telegram bot runtime."""

from __future__ import annotations

import os
from urllib.parse import urlparse

from ...download.transfer import javascript_runtime_options

SUPPORTED_COOKIE_BROWSERS = frozenset(
    {"brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi", "whale"}
)
YOUTUBE_HOSTS = frozenset({"youtube.com", "youtu.be", "youtube-nocookie.com"})


class _PrivacySafeYtDlpLogger:
    """Discard provider-controlled yt-dlp text from normal bot output."""

    @staticmethod
    def debug(message: str) -> None:
        """Discard a debug message."""

        del message

    @staticmethod
    def info(message: str) -> None:
        """Discard an informational message."""

        del message

    @staticmethod
    def warning(message: str) -> None:
        """Discard a warning message."""

        del message

    @staticmethod
    def error(message: str) -> None:
        """Discard an error message."""

        del message


_PRIVACY_SAFE_LOGGER = _PrivacySafeYtDlpLogger()


def configured_cookie_browser(value: str | None = None) -> str | None:
    """Return the validated browser name for optional local cookie access."""

    raw_value = (
        os.getenv("PRIVATE_SEARCH_YTDLP_COOKIES_FROM_BROWSER", "")
        if value is None
        else value
    )
    browser = raw_value.strip().casefold()
    if not browser:
        return None
    if browser not in SUPPORTED_COOKIE_BROWSERS:
        supported = ", ".join(sorted(SUPPORTED_COOKIE_BROWSERS))
        raise ValueError(
            "PRIVATE_SEARCH_YTDLP_COOKIES_FROM_BROWSER must be one of: "
            f"{supported}"
        )
    return browser


def _is_youtube_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").casefold().rstrip(".")
    return host in YOUTUBE_HOSTS or any(host.endswith(f".{domain}") for domain in YOUTUBE_HOSTS)


def browser_cookie_options(url: str) -> dict[str, object]:
    """Return ephemeral browser-cookie options for YouTube only.

    The browser name is the only credential-related setting. yt-dlp reads the
    browser's local cookie database; this process never receives a cookie-file
    path and never persists the extracted cookies.
    """

    if not _is_youtube_url(url):
        return {}
    browser = configured_cookie_browser()
    if browser is None:
        return {}
    profile = os.getenv("PRIVATE_SEARCH_YTDLP_COOKIES_BROWSER_PROFILE", "").strip() or None
    return {
        "cookiesfrombrowser": (browser, profile, None, None),
        "cachedir": False,
    }


def privacy_safe_logger_options() -> dict[str, object]:
    """Keep provider-controlled IDs, titles, and URLs out of bot stderr."""

    return {"logger": _PRIVACY_SAFE_LOGGER}


__all__ = [
    "browser_cookie_options",
    "configured_cookie_browser",
    "javascript_runtime_options",
    "privacy_safe_logger_options",
]
