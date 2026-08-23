"""Normalize yt-dlp formats into user-selectable quality options."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

BEST_AVAILABLE_KEY = "best"


@dataclass(frozen=True, slots=True)
class QualityOption:
    """One source format choice shown to a Telegram user."""

    key: str
    label: str
    height: int | None
    size_bytes: int | None
    size_approximate: bool
    format_selector: str
    media_type: str
    audio_format: str | None = None


def positive_int(value: object) -> int | None:
    """Normalize one positive integer field from untrusted extractor metadata."""

    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _size(item: Mapping[str, object]) -> tuple[int | None, bool]:
    exact = positive_int(item.get("filesize"))
    if exact is not None:
        return exact, False
    approximate = positive_int(item.get("filesize_approx"))
    return approximate, approximate is not None


def _codec_present(value: object) -> bool:
    return bool(value and value != "none")


def _is_hls(item: Mapping[str, object]) -> bool:
    protocol = str(item.get("protocol") or "").casefold()
    return "m3u8" in protocol


def _has_video(item: Mapping[str, object], height: int | None) -> bool:
    """Recognize video formats whose extractor omits optional codec labels."""

    return height is not None and (
        _codec_present(item.get("vcodec"))
        or not _codec_present(item.get("acodec"))
    )


def _candidate_rank(item: Mapping[str, object]) -> tuple[int, int, int, float]:
    size_bytes, _ = _size(item)
    raw_tbr = item.get("tbr")
    try:
        bitrate = float(raw_tbr) if raw_tbr is not None else 0.0
    except (TypeError, ValueError):
        bitrate = 0.0
    return (
        int(not _is_hls(item)),
        int(_codec_present(item.get("acodec"))),
        int(size_bytes is not None),
        bitrate,
    )


def _estimated_audio_size(
    info: Mapping[str, object],
    source_size_bytes: int | None,
    bitrate_kbps: int,
) -> tuple[int | None, bool]:
    """Estimate a converted lossy output without claiming exact size."""

    try:
        duration = float(info.get("duration"))
    except (TypeError, ValueError):
        duration = 0.0
    if duration > 0:
        return int(duration * bitrate_kbps * 1000 / 8), True
    if source_size_bytes is not None:
        return source_size_bytes, True
    return None, False


def format_size(size_bytes: int | None, approximate: bool = False) -> str:
    """Return a compact binary size label for a Telegram button."""

    if size_bytes is None:
        return "size unknown"
    value = float(size_bytes)
    units = ("B", "KB", "MB", "GB")
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    prefix = "~" if approximate else ""
    if unit_index == 0:
        return f"{prefix}{int(value)} {units[unit_index]}"
    return f"{prefix}{value:.1f} {units[unit_index]}"


def _best_available_options(
    size_bytes: int | None, max_output_bytes: int
) -> tuple[QualityOption, ...]:
    exact_size = positive_int(size_bytes)
    if exact_size is None or exact_size > max_output_bytes:
        return ()
    return (
        QualityOption(
            key=BEST_AVAILABLE_KEY,
            label="Best available",
            height=None,
            size_bytes=exact_size,
            size_approximate=False,
            format_selector="bestvideo+bestaudio/best",
            media_type="video",
        ),
    )


# pylint: disable=too-many-locals
def build_quality_options(
    info: Mapping[str, object],
    max_output_bytes: int,
    *,
    best_available_size_bytes: int | None = None,
) -> tuple[QualityOption, ...]:
    """Build deduplicated, source-available video and MP3 choices."""

    raw_formats = info.get("formats")
    if not isinstance(raw_formats, list):
        raw_formats = []

    video_by_height: dict[int, Mapping[str, object]] = {}
    audio_candidates: list[Mapping[str, object]] = []
    for raw_item in raw_formats:
        if not isinstance(raw_item, Mapping):
            continue
        format_id = raw_item.get("format_id")
        if not format_id:
            continue
        height = positive_int(raw_item.get("height"))
        has_video = _has_video(raw_item, height)
        has_audio = _codec_present(raw_item.get("acodec"))
        if has_video:
            current = video_by_height.get(height)
            if current is None or _candidate_rank(raw_item) > _candidate_rank(current):
                video_by_height[height] = raw_item
        if has_audio and not _codec_present(raw_item.get("vcodec")):
            audio_candidates.append(raw_item)

    options: list[QualityOption] = []
    for height in sorted(video_by_height, reverse=True):
        item = video_by_height[height]
        size_bytes, approximate = _size(item)
        if size_bytes is not None and size_bytes > max_output_bytes:
            continue
        format_id = str(item["format_id"])
        selector = format_id
        if item.get("acodec") == "none":
            selector = f"{format_id}+bestaudio/best"
        options.append(
            QualityOption(
                key=f"v{height}",
                label=f"{height}p",
                height=height,
                size_bytes=size_bytes,
                size_approximate=approximate,
                format_selector=selector,
                media_type="video",
            )
        )

    if audio_candidates:
        audio = max(audio_candidates, key=_candidate_rank)
        source_size_bytes, _ = _size(audio)
        format_selector = str(audio["format_id"])
        audio_choices = (
            ("mp3", "MP3 (192 kbps)", 192, "audio"),
            ("m4a", "M4A (AAC 256 kbps)", 256, "audio"),
            ("flac", "FLAC (lossless)", None, "document"),
            ("alac", "ALAC (lossless)", None, "document"),
        )
        for key, label, bitrate_kbps, media_type in audio_choices:
            if bitrate_kbps is None:
                size_bytes, approximate = None, False
            else:
                size_bytes, approximate = _estimated_audio_size(
                    info, source_size_bytes, bitrate_kbps
                )
            if size_bytes is not None and size_bytes > max_output_bytes:
                continue
            options.append(
                QualityOption(
                    key=key,
                    label=label,
                    height=None,
                    size_bytes=size_bytes,
                    size_approximate=approximate,
                    format_selector=format_selector,
                    media_type=media_type,
                    audio_format=key,
                )
            )
    return tuple(options) or _best_available_options(
        best_available_size_bytes, max_output_bytes
    )
