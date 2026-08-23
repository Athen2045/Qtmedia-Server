"""Small PMVHaven metadata adapter.

The CommunityScrapers PMVHaven scraper documents the public video metadata
endpoint. This adapter deliberately uses it only for a known video URL; the
endpoint is not treated as a general search API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

VIDEO_PATH_PATTERN = re.compile(r"^/video/", re.IGNORECASE)
VIDEO_ID_PATTERN = re.compile(
    r"(?P<video_id>[a-f0-9]{24})(?:[^a-f0-9]|$)", re.IGNORECASE
)
API_TEMPLATE = "https://pmvhaven.com/api/videos/{video_id}"
MEDIA_DOMAINS = frozenset(
    {"pmvhavencloud.s3.eu-west-par.io.cloud.ovh.net"}
)
REQUEST_TIMEOUT = 20


@dataclass(frozen=True)
# pylint: disable=too-many-instance-attributes
class PMVHavenMetadata:
    """Normalized metadata returned by PMVHaven's video endpoint."""

    video_id: str
    title: str
    url: str
    thumbnail_url: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()
    performers: tuple[str, ...] = ()
    video_url: str | None = None
    hls_master_url: str | None = None

    @property
    def media_url(self) -> str | None:
        """Prefer the quality-bearing HLS manifest over the direct MP4."""

        return self.hls_master_url or self.video_url


def is_pmvhaven_url(url: str) -> bool:
    """Return whether a URL has PMVHaven's supported video-page shape."""

    host = urlparse(url).netloc.casefold().removeprefix("www.")
    path = urlparse(url).path
    return (
        host == "pmvhaven.com"
        and VIDEO_PATH_PATTERN.search(path) is not None
        and VIDEO_ID_PATTERN.search(path) is not None
    )


def extract_video_id(url: str) -> str | None:
    """Extract a supported PMVHaven object identifier from a video URL."""

    path = urlparse(url).path
    if not VIDEO_PATH_PATTERN.search(path):
        return None
    match = VIDEO_ID_PATTERN.search(path)
    return match.group("video_id") if match else None


def fetch_metadata(
    url: str, session: requests.Session | None = None
) -> PMVHavenMetadata:
    """Fetch normalized metadata for one recognized PMVHaven video URL."""

    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError("URL does not contain a 24-character PMVHaven video ID")

    client = session or requests.Session()
    response = client.get(
        API_TEMPLATE.format(video_id=video_id),
        headers={"User-Agent": "qtmedia-cli/0.1"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise TypeError("PMVHaven API returned an unexpected response")

    title = str(data.get("title") or video_id).strip()
    tags = tuple(str(item) for item in (data.get("tags") or []) if item)
    performers = tuple(str(item) for item in (data.get("starsTags") or []) if item)
    return PMVHavenMetadata(
        video_id=video_id,
        title=title,
        url=f"https://pmvhaven.com/video/{video_id}",
        thumbnail_url=data.get("thumbnailUrl"),
        description=data.get("description"),
        tags=tags,
        performers=performers,
        video_url=data.get("videoUrl"),
        hls_master_url=data.get("hlsMasterPlaylistUrl"),
    )
