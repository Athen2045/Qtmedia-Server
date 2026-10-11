"""Opt-in Firefox cookies for sites behind a Cloudflare challenge.

Cloudflare answers some networks (VPN exit IPs especially) with a JavaScript
challenge no HTTP client can pass. A browser on the same network can, and the
``cf_clearance`` cookie it receives is valid for the same IP *and user agent*.
With ``QTMEDIA_COOKIES_BROWSER=firefox`` the engine reads the active Firefox
profile's cookies (in memory, via yt-dlp) for adapters marked
``browser_cookies``, presents that Firefox's exact user agent, and uses a
Firefox TLS fingerprint so the request looks like the browser that earned the
cookie. Cookies are never copied, logged, or sent to other sites.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from ..net import http_client
from .adapters import adapter_for_host

COOKIES_ENV = "QTMEDIA_COOKIES_BROWSER"
SUPPORTED_BROWSERS = frozenset({"firefox"})
LAST_VERSION = re.compile(r"^LastVersion=(\d+)\.", re.MULTILINE)


@dataclass(frozen=True)
class FirefoxProfile:
    path: Path
    major_version: int

    @property
    def user_agent(self) -> str:
        # Firefox reports only the major version ("rv:157.0"), on every
        # Windows build, so this matches what the browser sent Cloudflare.
        version = f"{self.major_version}.0"
        return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{version}) Gecko/20100101 Firefox/{version}"


def configured_browser() -> str | None:
    value = os.getenv(COOKIES_ENV, "").strip().casefold()
    return value if value in SUPPORTED_BROWSERS else None


def _profiles_root() -> Path | None:
    appdata = os.getenv("APPDATA")
    return Path(appdata) / "Mozilla" / "Firefox" / "Profiles" if appdata else None


def active_firefox_profile(root: Path | None = None) -> FirefoxProfile | None:
    """The profile Firefox used most recently: the newest ``cookies.sqlite``.

    yt-dlp makes the same choice when given no profile; naming it explicitly
    lets the user agent come from the same profile's ``compatibility.ini``.
    """
    root = root if root is not None else _profiles_root()
    if root is None or not root.is_dir():
        return None
    newest: tuple[float, Path] | None = None
    for cookies in root.glob("*/cookies.sqlite"):
        try:
            modified = cookies.stat().st_mtime
        except OSError:
            continue
        if newest is None or modified > newest[0]:
            newest = (modified, cookies.parent)
    if newest is None:
        return None
    try:
        compatibility = (newest[1] / "compatibility.ini").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = LAST_VERSION.search(compatibility)
    return FirefoxProfile(newest[1], int(match.group(1))) if match else None


def site_ydl_options(url: str) -> dict[str, object]:
    """yt-dlp options for reaching ``url``'s site: impersonation and, when the
    user opted in and the adapter allows it, Firefox cookies.

    Raises ``ValueError("cookies_unavailable")`` when cookies are on for this
    site but no Firefox profile can be read, rather than silently sending a
    request Cloudflare will refuse.
    """
    adapter = adapter_for_host(urlparse(url).hostname or "")
    options: dict[str, object] = {}
    profile_name = adapter.impersonate if adapter else None
    if adapter is not None and adapter.browser_cookies and configured_browser() == "firefox":
        profile = active_firefox_profile()
        if profile is None:
            raise ValueError("cookies_unavailable")
        options.update(
            {
                "cookiesfrombrowser": ("firefox", str(profile.path), None, None),
                "http_headers": {"User-Agent": profile.user_agent},
                # Keep nothing derived from the cookies on disk.
                "cachedir": False,
            }
        )
        profile_name = "firefox"
    target = http_client.ytdlp_impersonate_target(profile_name) if profile_name else None
    if target:
        from yt_dlp.networking.impersonate import (  # pylint: disable=import-outside-toplevel
            ImpersonateTarget,
        )

        options["impersonate"] = ImpersonateTarget.from_str(target)
    return options
