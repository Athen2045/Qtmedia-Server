"""Fixed-root media library scanning and path confinement."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Literal

MediaType = Literal["audio", "video"]
MEDIA_EXTENSIONS = {
    "audio": frozenset({".mp3"}),
    "video": frozenset({".mp4"}),
}
ARTWORK_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


class LibraryError(ValueError):
    pass


@dataclass(frozen=True)
class LibraryEntry:
    relative_path: str
    media_type: MediaType
    extension: str
    size_bytes: int
    modified_at: float
    duration_seconds: int | None = None
    artwork_path: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "media_type": self.media_type,
            "extension": self.extension,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
            "duration_seconds": self.duration_seconds,
            "artwork_path": self.artwork_path,
        }


def confined_path(root: Path, relative: str) -> Path:
    raw = PurePath(relative)
    if raw.is_absolute() or raw.drive or ".." in raw.parts:
        raise LibraryError("path_escape")
    resolved_root = root.resolve()
    candidate = (resolved_root / Path(*raw.parts)).resolve(strict=False)
    try:
        if os.path.commonpath((resolved_root, candidate)) != str(resolved_root):
            raise LibraryError("path_escape")
    except ValueError as error:
        raise LibraryError("path_escape") from error
    return candidate


def _media_files(root: Path, media_type: MediaType):
    directory = root / media_type
    if not directory.exists():
        return
    for path in directory.iterdir():
        if path.is_file() and path.suffix.casefold() in MEDIA_EXTENSIONS[media_type]:
            yield path


def scan_library(root: Path) -> tuple[LibraryEntry, ...]:
    resolved_root = root.resolve()
    entries: list[LibraryEntry] = []
    for media_type in ("audio", "video"):
        for path in _media_files(resolved_root, media_type):
            safe = confined_path(resolved_root, path.relative_to(resolved_root).as_posix())
            stat = safe.stat()
            artwork_path = next(
                (
                    candidate.relative_to(resolved_root).as_posix()
                    for extension in ARTWORK_EXTENSIONS
                    if (candidate := resolved_root / "artwork" / f"{safe.stem}{extension}").is_file()
                    and not candidate.is_symlink()
                ),
                None,
            )
            entries.append(
                LibraryEntry(
                    relative_path=safe.relative_to(resolved_root).as_posix(),
                    media_type=media_type,
                    extension=safe.suffix.removeprefix(".").casefold(),
                    size_bytes=stat.st_size,
                    modified_at=stat.st_mtime,
                    artwork_path=artwork_path,
                )
            )
    return tuple(sorted(entries, key=lambda entry: entry.relative_path.casefold()))
