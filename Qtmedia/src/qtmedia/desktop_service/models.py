"""Typed values shared across desktop inspection, transfer, and storage."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

MediaKind = Literal["audio", "video"]


@dataclass(frozen=True)
class FormatOption:
    key: str
    label: str
    extension: str
    kind: MediaKind | None = None
    height: int | None = None
    bitrate_kbps: int | None = None

    def __post_init__(self) -> None:
        if self.kind is None and self.key in {"audio", "video"}:
            object.__setattr__(self, "kind", self.key)
        if self.kind not in {"audio", "video"}:
            raise ValueError("invalid_format")

    def as_dict(self) -> dict[str, str | int | None]:
        return {
            "key": self.key,
            "kind": self.kind,
            "label": self.label,
            "extension": self.extension,
            "height": self.height,
            "bitrate_kbps": self.bitrate_kbps,
        }


@dataclass(frozen=True)
class FormatSelection:
    key: str
    kind: MediaKind
    selector: str
    extension: str


@dataclass(frozen=True)
class InspectionResult:
    title: str
    site: str
    duration_seconds: int | None
    formats: tuple[FormatOption, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "site": self.site,
            "duration_seconds": self.duration_seconds,
            "formats": [item.as_dict() for item in self.formats],
        }


@dataclass(frozen=True)
class InspectedMedia:
    source_url: str
    media_id: str
    title: str
    site: str
    thumbnail_url: str | None
    duration_seconds: int | None = None
    download_url: str | None = None
    formats: tuple[FormatOption, ...] = field(default_factory=tuple)
    selections: Mapping[str, FormatSelection] = field(default_factory=dict, repr=False, compare=False)

    def selection_for(self, format_key: str) -> FormatSelection:
        selection = self.selections.get(format_key)
        if selection is not None:
            return selection
        option = next((item for item in self.formats if item.key == format_key), None)
        if option is None or option.kind is None:
            raise ValueError("format_unavailable")
        fallback = "bestaudio/best" if option.kind == "audio" else "bestvideo+bestaudio/best"
        return FormatSelection(option.key, option.kind, fallback, option.extension)


@dataclass(frozen=True)
class Inspection:
    media: InspectedMedia
    result: InspectionResult


@dataclass(frozen=True)
class DownloadProgress:
    downloaded_bytes: int
    total_bytes: int | None
    percent: float | None

    def as_dict(self) -> dict[str, int | float | None]:
        return {
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "percent": self.percent,
        }


@dataclass(frozen=True)
class DownloadResult:
    relative_path: str
    title: str
    media_type: MediaKind
    extension: str
    artwork_path: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "relative_path": self.relative_path,
            "title": self.title,
            "media_type": self.media_type,
            "extension": self.extension,
            "artwork_path": self.artwork_path,
        }


@dataclass(frozen=True)
class MediaLibrary:
    root: Path
    audio: Path
    video: Path
    artwork: Path
    temp: Path

    @classmethod
    def create(cls, root: Path) -> MediaLibrary:
        resolved = root.expanduser().resolve()
        library = cls(
            root=resolved,
            audio=resolved / "audio",
            video=resolved / "video",
            artwork=resolved / "artwork",
            temp=resolved / "temp",
        )
        for directory in (library.audio, library.video, library.artwork, library.temp):
            directory.mkdir(parents=True, exist_ok=True)
        for stale in library.temp.iterdir():
            if stale.is_symlink() or stale.is_file():
                stale.unlink(missing_ok=True)
            elif stale.is_dir():
                shutil.rmtree(stale)
        return library
