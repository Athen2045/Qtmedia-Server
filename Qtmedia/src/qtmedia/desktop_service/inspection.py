"""Display-safe direct-link inspection for desktop callers."""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from urllib.parse import unquote_plus, urlsplit

import requests

from ..download.transfer import common_ydl_options
from ..net import http_client
from ..sources.pmvhaven import fetch_metadata, is_pmvhaven_url
from .browser_cookies import site_ydl_options
from .models import (
    FormatOption,
    FormatSelection,
    InspectedMedia,
    Inspection,
    InspectionResult,
    MediaKind,
)
from .network import apply_proxy, proxy_options
from .policy import AdapterPolicy
from .runtime import javascript_runtime_options
from .song_tags import song_tags
from .ytdlp_errors import failure_code

Extractor = Callable[[str, dict[str, object]], dict[str, object]]


def _desktop_ydl_options(url: str) -> dict[str, object]:
    options: dict[str, object] = {
        **common_ydl_options(),
        **javascript_runtime_options(),
        **proxy_options(),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extractor_retries": http_client.RETRY_ATTEMPTS,
    }
    # Impersonation, and the user's Firefox cookies where opted in.
    options.update(site_ydl_options(url))
    return options


def _extract_with_ytdlp(url: str, options: dict[str, object]) -> dict[str, object]:
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as error:
        raise ValueError(failure_code(error)) from error
    if not isinstance(info, dict):
        raise ValueError("no_formats")  # noqa: TRY004
    return info


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


# yt-dlp reports an absent stream as "none" and an undeclared codec as None.
# HLS manifests without CODECS (e.g. PMVHaven) give None for muxed variants.
HEIGHT_LABEL = re.compile(r"(?<!\d)(\d{3,4})p(?![a-z])", re.IGNORECASE)


def _height(item: dict[str, object]) -> int | None:
    """The variant height, or one named in the format ID/note (e.g. ``720p_60fps``)."""
    raw = item.get("height")
    if isinstance(raw, (int, float)) and raw > 0:
        return int(raw)
    for field in ("format_id", "format_note"):
        match = HEIGHT_LABEL.search(str(item.get(field) or ""))
        if match:
            return int(match.group(1))
    return None


VIDEO_EXTENSIONS = frozenset({"mp4", "m4v", "webm", "mkv", "mov", "flv"})


def _has_video(item: dict[str, object]) -> bool:
    vcodec = item.get("vcodec")
    if vcodec == "none":
        return False
    if vcodec is not None or _height(item) is not None:
        return True
    # A plain file with no codec or size details at all (the Txxx network's
    # "hq.mp4") is an ordinary muxed video.
    return item.get("acodec") is None and item.get("ext") in VIDEO_EXTENSIONS


def _has_audio(item: dict[str, object]) -> bool:
    acodec = item.get("acodec")
    if acodec == "none":
        return False
    if acodec is not None:
        return True
    # Undeclared codecs on a video variant mean a muxed stream.
    return item.get("vcodec") is None and _has_video(item)


# At equal height prefer codecs that system players handle best.
VIDEO_CODEC_RANK = (("avc1", 3), ("h264", 3), ("vp09", 2), ("vp9", 2), ("av01", 1))
AUDIO_CODEC_NAMES = (("opus", "Opus"), ("mp4a", "AAC"), ("aac", "AAC"), ("vorbis", "Vorbis"), ("mp3", "MP3"), ("flac", "FLAC"))


def _codec_rank(item: dict[str, object]) -> int:
    codec = str(item.get("vcodec") or "").casefold()
    return next((rank for prefix, rank in VIDEO_CODEC_RANK if codec.startswith(prefix)), 0)


def _video_rank(item: dict[str, object]) -> tuple[int, int, float, int, float]:
    extension = str(item.get("ext") or "").casefold()
    extension_rank = {"mp4": 3, "m4v": 2, "webm": 1}.get(extension, 0)
    has_audio = int(_has_audio(item))
    return (extension_rank, has_audio, float(_height(item) or 0), _codec_rank(item), _number(item.get("tbr")))


def _source_label(target: str, item: dict[str, object]) -> str:
    """Saved audio is labelled with the stream it comes from, never "lossless"."""
    codec = str(item.get("acodec") or "").casefold()
    name = next((label for prefix, label in AUDIO_CODEC_NAMES if codec.startswith(prefix)), None)
    if name is None:
        return target
    bitrate = _number(item.get("abr"))
    return f"{target} · from {name} {round(bitrate)} kbps" if bitrate else f"{target} · from {name}"


def _flac_label(item: dict[str, object]) -> str:
    return _source_label("FLAC", item)


# How much each lossy codec delivers per kbps, relative to AAC-LC: Opus is
# transparent at lower bitrates than AAC, which beats MP3; HE-AAC (mp4a.40.5)
# trades fidelity for size. Lossless sources always win.
CODEC_EFFICIENCY = (
    ("flac", 100.0), ("alac", 100.0), ("pcm", 100.0), ("wav", 100.0),
    ("opus", 1.4), ("vorbis", 1.15), ("mp4a.40.5", 0.7), ("mp4a", 1.0), ("aac", 1.0), ("mp3", 0.85),
)


def _is_drc(item: dict[str, object]) -> bool:
    """YouTube's dynamic-range-compressed variants (format id ``251-drc``)."""
    format_id = str(item.get("format_id") or "").casefold()
    note = str(item.get("format_note") or "").casefold()
    return format_id.endswith("-drc") or "drc" in note.replace(",", " ").split()


def _audio_rank(item: dict[str, object]) -> tuple[int, int, float, float, float, float]:
    """Best listening quality first: audio-only, not DRC, the original-language
    track, the site's own quality tier, codec-weighted bitrate, sample rate."""
    audio_only = int(not _has_video(item))
    codec = str(item.get("acodec") or "").casefold()
    efficiency = next((weight for prefix, weight in CODEC_EFFICIENCY if codec.startswith(prefix)), 1.0)
    bitrate = _number(item.get("abr")) or _number(item.get("tbr"))
    return (
        audio_only,
        int(not _is_drc(item)),
        _number(item.get("language_preference")),
        _number(item.get("quality")),
        bitrate * efficiency,
        _number(item.get("asr")),
    )


def _selector(
    item: dict[str, object],
    kind: MediaKind,
    height: int | None,
    best_audio: str | None = None,
) -> str:
    format_id = item.get("format_id")
    if isinstance(format_id, str) and format_id.strip():
        if kind == "audio":
            return format_id
        if _has_audio(item):
            return format_id
        # The best-sounding track (usually Opus; MP4 holds it and the player
        # plays it), else whatever audio the source has.
        if best_audio:
            return f"{format_id}+{best_audio}/{format_id}+bestaudio"
        return f"{format_id}+bestaudio"
    if kind == "video" and height is not None:
        return f"bestvideo[height={height}]+bestaudio"
    return "bestaudio" if kind == "audio" else "bestvideo+bestaudio"


SLUG_SEPARATORS = re.compile(r"[-_+\s]+")
# "+" between words, as in a form-encoded query. NoodleMagazine page titles
# arrive as "Best+pmv+teen+hot 4k".
PLUS_JOINED = re.compile(r"(?<=[^\s+])\+(?=[^\s+])")


def _display_title(info: dict[str, object], page_url: str) -> str:
    """The extractor's title, or a readable one from the URL slug.

    Some extractors (SpankBang) fall back to the video ID when the page title
    cannot be parsed; the slug in the page URL is the better name then.
    """
    raw = str(info.get("title") or "").strip()
    ids = {str(info.get(key) or "").strip() for key in ("id", "display_id")} - {""}
    if len(PLUS_JOINED.findall(raw)) >= 2:
        # Two or more joins means an encoded title; one may be real ("A+B").
        raw = PLUS_JOINED.sub(" ", raw)
    if raw and raw not in ids:
        return raw
    segments = [segment for segment in urlsplit(page_url).path.split("/") if segment]
    slug = SLUG_SEPARATORS.sub(" ", unquote_plus(segments[-1])).strip() if segments else ""
    slug = re.sub(r"\.html?$", "", slug, flags=re.IGNORECASE)
    if slug and slug not in ids and not slug.isdigit():
        return slug[0].upper() + slug[1:]
    return raw or "Untitled media"


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
    video_candidates = [item for item in candidates if _has_video(item)]
    audio_candidates = [item for item in candidates if _has_audio(item)]
    audio_only = [item for item in audio_candidates if not _has_video(item)]
    best_audio_item = max(audio_only, key=_audio_rank) if audio_only else None
    best_audio_id = best_audio_item.get("format_id") if best_audio_item else None
    best_audio = best_audio_id if isinstance(best_audio_id, str) and best_audio_id.strip() else None
    available: list[FormatOption] = []
    selections: dict[str, FormatSelection] = {}
    used_keys: set[str] = set()
    by_height: dict[int | None, dict[str, object]] = {}
    for item in video_candidates:
        height = _height(item)
        current = by_height.get(height)
        if current is None or _video_rank(item) > _video_rank(current):
            by_height[height] = item
    for height in sorted((value for value in by_height if value is not None), reverse=True):
        item = by_height[height]
        key = _new_key(used_keys)
        option = FormatOption(key, f"{height}p MP4", "mp4", "video", height, None)
        available.append(option)
        selections[key] = FormatSelection(key, "video", _selector(item, "video", height, best_audio), "mp4")
    # A file of unknown quality is offered only when nothing else is: next to
    # labelled heights it is a duplicate the user cannot judge (XNXX's
    # "low"/"high" files beside its 250p-1080p streams).
    if None in by_height and len(by_height) == 1:
        item = by_height[None]
        key = _new_key(used_keys)
        option = FormatOption(key, "Video MP4", "mp4", "video", None, None)
        available.append(option)
        selections[key] = FormatSelection(key, "video", _selector(item, "video", None, best_audio), "mp4")
    if audio_candidates:
        item = max(audio_candidates, key=_audio_rank)
        # Music is saved as FLAC only: it keeps every bit of the best stream
        # (no second lossy encode). The MP3 path in download.py stays for
        # selections made before this change.
        key = _new_key(used_keys)
        available.append(FormatOption(key, _flac_label(item), "flac", "audio", None, None))
        selections[key] = FormatSelection(key, "audio", _selector(item, "audio", None), "flac")
    return tuple(available), selections


def inspect_url(
    url: str,
    policy: AdapterPolicy,
    *,
    extractor: Extractor | None = None,
) -> Inspection:
    approved = policy.validate(url)
    download_url: str | None = None
    extract = extractor or _extract_with_ytdlp

    if is_pmvhaven_url(url):
        # yt-dlp has no PMVHaven extractor; read the page API for the manifest,
        # then let yt-dlp list the manifest's real variants so format IDs match
        # what the download will request.
        try:
            metadata = fetch_metadata(url, session=apply_proxy(requests.Session()))
        except requests.RequestException as error:
            # Same stable code as yt-dlp extraction failures: the source is unreachable.
            raise ValueError("provider_unavailable") from error
        download_url = metadata.media_url
        if not download_url:
            raise ValueError("no_formats")
        info = dict(extract(download_url, _desktop_ydl_options(download_url)))
        info["title"] = metadata.title
        info["thumbnail"] = metadata.thumbnail_url
    else:
        # The approved URL is canonical (e.g. a SpankBang mirror rewritten to
        # spankbang.com), so yt-dlp's site extractor recognises it.
        info = extract(approved.url, _desktop_ydl_options(approved.url))

    formats, selections = _available_formats(info)
    if not formats:
        raise ValueError("no_formats")
    title = _display_title(info, approved.url)
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
        tags=song_tags(info),
    )
    return Inspection(media=media, result=result)
