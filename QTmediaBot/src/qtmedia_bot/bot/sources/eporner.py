"""Eporner page variants for the Telegram bot inspection seam.

yt-dlp remains responsible for extracting metadata and formats. This module
only recognizes the provider's page shapes and offers the documented embed
variant as a bounded fallback when the ordinary page has changed layout.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

VIDEO_ID_PATTERN = re.compile(
    r"/(?:video-|hd-porn/|embed/)(?P<video_id>[A-Za-z0-9_]+)(?:/|$)",
    re.IGNORECASE,
)
PAGE_HOSTS = frozenset({"eporner.com", "www.eporner.com"})


class EpornerAdapter:
    """Recognize Eporner pages without duplicating yt-dlp's extractor."""

    @staticmethod
    def video_id(url: str) -> str | None:
        """Return the Eporner video ID from a supported page URL."""

        parsed = urlsplit(url)
        if (parsed.hostname or "").casefold().rstrip(".") not in PAGE_HOSTS:
            return None
        match = VIDEO_ID_PATTERN.search(parsed.path)
        return match.group("video_id") if match else None

    @classmethod
    def alternate_urls(cls, url: str) -> tuple[str, ...]:
        """Return the provider embed page for the same video, if applicable."""

        video_id = cls.video_id(url)
        if not video_id or "/embed/" in urlsplit(url).path.casefold():
            return ()
        return (f"https://www.eporner.com/embed/{video_id}",)
