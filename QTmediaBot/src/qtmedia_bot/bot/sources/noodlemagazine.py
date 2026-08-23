"""NoodleMagazine page variants for the Telegram bot inspection seam."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

VIDEO_ID_PATTERN = re.compile(r"^/watch/(?P<video_id>[0-9_-]+)(?:/|$)", re.IGNORECASE)
PAGE_HOSTS = frozenset(
    {
        "noodlemagazine.com",
        "www.noodlemagazine.com",
        "adult.noodlemagazine.com",
    }
)


class NoodleMagazineAdapter:
    """Recognize NoodleMagazine hosts without reimplementing its extractor."""

    @staticmethod
    def video_id(url: str) -> str | None:
        """Return the NoodleMagazine video ID from a supported page URL."""

        parsed = urlsplit(url)
        if (parsed.hostname or "").casefold().rstrip(".") not in PAGE_HOSTS:
            return None
        match = VIDEO_ID_PATTERN.match(parsed.path)
        return match.group("video_id") if match else None

    @classmethod
    def alternate_urls(cls, url: str) -> tuple[str, ...]:
        """Try the provider's public and adult page hosts for one video ID."""

        video_id = cls.video_id(url)
        if not video_id:
            return ()
        current_host = (urlsplit(url).hostname or "").casefold().rstrip(".")
        return tuple(
            f"https://{host}/watch/{video_id}"
            for host in ("adult.noodlemagazine.com", "www.noodlemagazine.com")
            if host != current_host
        )
