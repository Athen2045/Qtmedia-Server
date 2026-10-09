"""Explicit desktop adapter allowlist and direct-link validation."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from ..search.engine import adapter_for_host, is_video_candidate
from ..sources.pmvhaven import is_pmvhaven_url


class DesktopPolicyError(ValueError):
    """A stable, display-safe desktop policy failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ApprovedSource:
    url: str
    site: str


YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"})
YOUTUBE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{6,}")


def _is_youtube_video_url(host: str, path: str, query: str) -> bool:
    """Accept common single-video YouTube URLs without accepting homepages/playlists."""
    normalized_path = path.rstrip("/")
    if host == "youtu.be":
        return YOUTUBE_ID_PATTERN.fullmatch(normalized_path.removeprefix("/")) is not None

    if normalized_path == "/watch":
        video_ids = parse_qs(query).get("v", [])
        return bool(video_ids and YOUTUBE_ID_PATTERN.fullmatch(video_ids[0]))

    for prefix in ("/shorts/", "/live/", "/embed/", "/v/"):
        if normalized_path.startswith(prefix):
            return YOUTUBE_ID_PATTERN.fullmatch(normalized_path.removeprefix(prefix)) is not None
    return False


class AdapterPolicy:
    """Approve only configured Qtmedia video-page adapters."""

    def validate(self, url: str) -> ApprovedSource:
        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").casefold().rstrip(".")
            _ = parsed.port
        except ValueError as error:
            raise DesktopPolicyError("invalid_url") from error

        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise DesktopPolicyError("invalid_url")

        if host == "localhost":
            raise DesktopPolicyError("unsupported_source")
        try:
            if ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback:
                raise DesktopPolicyError("unsupported_source")
        except ValueError:
            pass

        if is_pmvhaven_url(url):
            return ApprovedSource(url=url, site="PMVHaven")

        if host in YOUTUBE_HOSTS:
            if _is_youtube_video_url(host, parsed.path, parsed.query):
                return ApprovedSource(url=url, site="YouTube")
            raise DesktopPolicyError("unsupported_source")

        adapter = adapter_for_host(host)
        if adapter is None or not is_video_candidate(adapter, parsed.path.rstrip("/")):
            raise DesktopPolicyError("unsupported_source")
        return ApprovedSource(url=url, site=adapter.name)
