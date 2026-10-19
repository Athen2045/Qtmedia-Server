"""Sites the desktop app trusts, reviewed independently of the CLI's list.

A site added to the CLI's search adapters does not become a desktop source;
add it here after reviewing its video-page URL shape. PMVHaven and YouTube
have dedicated rules in ``policy.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class DesktopAdapter:
    name: str
    domain: str
    video_path: re.Pattern[str]
    excluded_path: re.Pattern[str] | None = None
    # curl_cffi fingerprint for sites that reject a plain TLS client.
    impersonate: str | None = None
    # Other domains serving the same site and URL shapes (e.g. "txxx.tube").
    aliases: tuple[str, ...] = ()
    # Use the user's Firefox cookies when they opt in (browser_cookies.py).
    # Only for sites whose Cloudflare challenge blocks some networks outright.
    browser_cookies: bool = False

    def matches_host(self, host: str) -> bool:
        host = host.casefold().rstrip(".").removeprefix("www.")
        return any(host == domain or host.endswith(f".{domain}") for domain in (self.domain, *self.aliases))

    def is_video_path(self, path: str) -> bool:
        if self.excluded_path and self.excluded_path.search(path):
            return False
        return self.video_path.search(path) is not None


DESKTOP_ADAPTERS: tuple[DesktopAdapter, ...] = (
    # A filtering network reset Python's TLS client on XVideos; curl_cffi passed.
    DesktopAdapter("XVideos", "xvideos.com", re.compile(r"/video(?:\.|\d)"), impersonate="chrome"),
    DesktopAdapter(
        "XHamster",
        "xhamster.com",
        re.compile(r"/videos/"),
        excluded_path=re.compile(r"/(?:creators|users|channels)/"),
    ),
    # SpankBang answers a plain client with Cloudflare's 403.
    DesktopAdapter(
        "SpankBang", "spankbang.com", re.compile(r"/video/"), impersonate="chrome", browser_cookies=True
    ),
    DesktopAdapter("TNAFlix", "tnaflix.com", re.compile(r"/[^/]+/[^/]+/video\d+|/video\d+")),
    DesktopAdapter("YouJizz", "youjizz.com", re.compile(r"/videos/")),
    DesktopAdapter("YouPorn", "youporn.com", re.compile(r"/watch/")),
    # yt-dlp's Eporner extractor accepts /video-<id>/ and /hd-porn/<id>/.
    DesktopAdapter("Eporner", "eporner.com", re.compile(r"^/(?:video-|hd-porn/)[A-Za-z0-9]+")),
    # yt-dlp's NoodleMagazine extractor accepts /watch/<owner>_<id>, where the
    # owner ID may be negative (VK-style IDs, e.g. /watch/-226552677_456244963).
    DesktopAdapter("NoodleMagazine", "noodlemagazine.com", re.compile(r"^/watch/-?\d+_\d+$")),
    # XNXX shares XVideos' infrastructure; yt-dlp wants /video-<id>/<slug>.
    DesktopAdapter("XNXX", "xnxx.com", re.compile(r"^/video-[0-9a-z]+(?:/|$)")),
    DesktopAdapter("RedTube", "redtube.com", re.compile(r"^/\d+$")),
    # Clips are /watch/<id> pages; /ifr/<id> is the embed player.
    DesktopAdapter("RedGifs", "redgifs.com", re.compile(r"^/(?:watch|ifr)/[A-Za-z0-9]+$")),
    # EMPFlix and MovieFap are TNAFlix's network, each with its own URL shape.
    DesktopAdapter("EMPFlix", "empflix.com", re.compile(r"^/(?:videos/.+-|[^/]+/[^/]+/video)\d+$")),
    DesktopAdapter("MovieFap", "moviefap.com", re.compile(r"^/videos/[0-9a-f]+/[^/]+\.html$")),
    DesktopAdapter("ThisVid", "thisvid.com", re.compile(r"^/videos/[A-Za-z0-9-]+$")),
    # yt-dlp's Txxx extractor covers this network: /video(s)/<id>/<slug> or
    # /video-<id>/, several sites also on a ".tube" domain.
    *(
        DesktopAdapter(name, domain, re.compile(r"^/videos?[/-]\d+(?:/|$)"), aliases=aliases)
        for name, domain, aliases in (
            ("HClips", "hclips.com", ()),
            ("HDZog", "hdzog.com", ("hdzog.tube",)),
            ("HotMovs", "hotmovs.com", ("hotmovs.tube",)),
            ("InPorn", "inporn.com", ()),
            ("PrivateHomeClips", "privatehomeclips.com", ()),
            ("TubePornClassic", "tubepornclassic.com", ()),
            ("Txxx", "txxx.com", ("txxx.tube",)),
            ("Upornia", "upornia.com", ("upornia.tube",)),
            ("VJAV", "vjav.com", ("vjav.tube",)),
            ("VXXX", "vxxx.com", ()),
            ("VoyeurHit", "voyeurhit.com", ("voyeurhit.tube",)),
        )
    ),
    # Not listed while yt-dlp's extractors are broken (checked 2026-10-18,
    # also on nightly 2026.10.10): Beeg (its API no longer returns streams),
    # Rule34Video (download-link markup changed), 4tube/PornTube/PornerBros/Fux
    # (moved to a JavaScript app).
)


def adapter_for_host(host: str) -> DesktopAdapter | None:
    return next((adapter for adapter in DESKTOP_ADAPTERS if adapter.matches_host(host)), None)


def impersonate_for_url(url: str) -> str | None:
    adapter = adapter_for_host(urlparse(url).hostname or "")
    return adapter.impersonate if adapter else None
