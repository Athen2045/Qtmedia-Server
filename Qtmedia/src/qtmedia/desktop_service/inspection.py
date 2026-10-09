"""Display-safe direct-link inspection for desktop callers."""

from __future__ import annotations

import secrets
from collections.abc import Callable

from ..download.transfer import common_ydl_options, javascript_runtime_options
from ..net import http_client
from ..search.engine import impersonate_for_url
from ..sources.pmvhaven import fetch_metadata, is_pmvhaven_url
from .models import (
    FormatOption,
    FormatSelection,
    InspectedMedia,
    Inspection,
    InspectionResult,
    MediaKind,
)
from .policy import AdapterPolicy

Extractor = Callable[[str, dict[str, object]], dict[str, object]]


def _desktop_ydl_options(url: str) -> dict[str, object]:
    options: dict[str, object] = {
        **common_ydl_options(),
        **javascript_runtime_options(),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extractor_retries": http_client.RETRY_ATTEMPTS,
    }
    profile = impersonate_for_url(url)
    target = http_client.ytdlp_impersonate_target(profile) if profile else None
    if target:
        from yt_dlp.networking.impersonate import (  # pylint: disable=import-outside-toplevel
            ImpersonateTarget,
        )

        options["impersonate"] = ImpersonateTarget.from_str(target)
    return options


def _extract_with_ytdlp(url: str, options: dict[str, object]) -> dict[str, object]:
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as error:
        raise ValueError("provider_unavailable") from error
    if not isinstance(info, dict):
        raise ValueError("no_formats")  # noqa: TRY004
    return info


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _video_rank(item: dict[str, object]) -> tuple[int, int, float, float]:
    extension = str(item.get("ext") or "").casefold()
    extension_rank = {"mp4": 3, "m4v": 2, "webm": 1}.get(extension, 0)
    has_audio = int(item.get("acodec") not in {None, "none"})
    return (extension_rank, has_audio, _number(item.get("height")), _number(item.get("tbr")))


def _audio_rank(item: dict[str, object]) -> tuple[int, float, float]:
    audio_only = int(item.get("vcodec") in {None, "none"})
    return (audio_only, _number(item.get("abr")), _number(item.get("tbr")))


def _selector(item: dict[str, object], kind: MediaKind, height: int | None) -> str:
    format_id = item.get("format_id")
    if isinstance(format_id, str) and format_id.strip():
        if kind == "audio":
            return format_id
        has_audio = item.get("acodec") not in {None, "none"}
        return format_id if has_audio else f"{format_id}+bestaudio[ext=m4a]"
    if kind == "video" and height is not None:
        return f"bestvideo[height={height}]+bestaudio"
    return "bestaudio" if kind == "audio" else "bestvideo+bestaudio"


def _new_key(used: set[str]) -> str:
    key = f"format-{secrets.token_urlsafe(9)}"
    while key in used:
        key = f"format-{secrets.token_urlsafe(9)}"
    used.add(key)
    return key


def _available_formats(
    info: dict[str, object],
) -> tuple[tuple[FormatOption, ...], dict[str, FormatSelection]]:
    raw_formats = info.get("formats")
    formats = raw_formats if isinstance(raw_formats, list) else [info]
    candidates = [item for item in formats if isinstance(item, dict)]
    video_candidates = [
        item for item in candidates if item.get("vcodec") not in {None, "none"}
    ]
    audio_candidates = [
        item for item in candidates if item.get("acodec") not in {None, "none"}
    ]
    available: list[FormatOption] = []
    selections: dict[str, FormatSelection] = {}
    used_keys: set[str] = set()
    by_height: dict[int | None, dict[str, object]] = {}
    for item in video_candidates:
        raw_height = item.get("height")
        height = int(raw_height) if isinstance(raw_height, (int, float)) and raw_height > 0 else None
        current = by_height.get(height)
        if current is None or _video_rank(item) > _video_rank(current):
            by_height[height] = item
    for height in sorted((value for value in by_height if value is not None), reverse=True):
        item = by_height[height]
        key = _new_key(used_keys)
        option = FormatOption(key, f"{height}p MP4", "mp4", "video", height, None)
        available.append(option)
        selections[key] = FormatSelection(key, "video", _selector(item, "video", height), "mp4")
    if None in by_height:
        item = by_height[None]
        key = _new_key(used_keys)
        option = FormatOption(key, "Video MP4", "mp4", "video", None, None)
        available.append(option)
        selections[key] = FormatSelection(key, "video", _selector(item, "video", None), "mp4")
    if audio_candidates:
        item = max(audio_candidates, key=_audio_rank)
        key = _new_key(used_keys)
        option = FormatOption(key, "MP3 · 192 kbps", "mp3", "audio", None, 192)
        available.append(option)
        selections[key] = FormatSelection(key, "audio", _selector(item, "audio", None), "mp3")
    return tuple(available), selections


def inspect_url(
    url: str,
    policy: AdapterPolicy,
    *,
    extractor: Extractor | None = None,
) -> Inspection:
    approved = policy.validate(url)
    download_url: str | None = None

    if extractor is None and is_pmvhaven_url(url):
        metadata = fetch_metadata(url)
        download_url = metadata.media_url
        info: dict[str, object] = {
            "title": metadata.title,
            "thumbnail": metadata.thumbnail_url,
            "formats": ([{"vcodec": "h264", "acodec": "aac"}] if download_url else []),
        }
    else:
        info = (extractor or _extract_with_ytdlp)(url, _desktop_ydl_options(url))

    formats, selections = _available_formats(info)
    if not formats:
        raise ValueError("no_formats")
    title = str(info.get("title") or "Untitled media").strip() or "Untitled media"
    raw_duration = info.get("duration")
    duration = int(raw_duration) if isinstance(raw_duration, (int, float)) else None
    thumbnail = info.get("thumbnail")
    thumbnail_url = str(thumbnail) if isinstance(thumbnail, str) else None
    media_id = f"media-{secrets.token_urlsafe(9)}"
    result = InspectionResult(title, approved.site, duration, formats)
    media = InspectedMedia(
        source_url=approved.url,
        media_id=media_id,
        title=title,
        site=approved.site,
        thumbnail_url=thumbnail_url,
        duration_seconds=duration,
        download_url=download_url,
        formats=formats,
        selections=selections,
    )
    return Inspection(media=media, result=result)
