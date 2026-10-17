"""Fixed-root media library scanning and path confinement."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Literal

MediaType = Literal["audio", "video"]
MEDIA_EXTENSIONS = {
    "audio": frozenset({".mp3", ".flac"}),
    "video": frozenset({".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi"}),
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
    """Yields ``(path, stat)`` for each media file directly in ``root/media_type``.

    One directory listing per folder: on Windows the listing already carries
    size and modified time, so plain files need no extra system calls. Plain
    files in the expected folder are confined by construction; symlinks, or a
    folder that resolves elsewhere, go through ``confined_path`` as before.
    """
    directory = root / media_type
    if not directory.exists():
        return
    in_place = directory.resolve() == root / media_type
    with os.scandir(directory) as listing:
        for entry in listing:
            if not entry.is_file() or os.path.splitext(entry.name)[1].casefold() not in MEDIA_EXTENSIONS[media_type]:
                continue
            if in_place and not entry.is_symlink():
                yield directory / entry.name, entry.stat()
            else:
                safe = confined_path(root, f"{media_type}/{entry.name}")
                yield safe, safe.stat()


def _artwork_names(root: Path) -> frozenset[str]:
    """Plain (non-symlink) files in ``root/artwork``, compared the way the OS does."""
    try:
        with os.scandir(root / "artwork") as listing:
            return frozenset(os.path.normcase(entry.name) for entry in listing if entry.is_file(follow_symlinks=False))
    except OSError:
        return frozenset()


def scan_library(root: Path) -> tuple[LibraryEntry, ...]:
    resolved_root = root.resolve()
    artwork = _artwork_names(resolved_root)
    entries: list[LibraryEntry] = []
    for media_type in ("audio", "video"):
        for path, stat in _media_files(resolved_root, media_type):
            artwork_path = next(
                (
                    f"artwork/{path.stem}{extension}"
                    for extension in ARTWORK_EXTENSIONS
                    if os.path.normcase(f"{path.stem}{extension}") in artwork
                ),
                None,
            )
            entries.append(
                LibraryEntry(
                    relative_path=path.relative_to(resolved_root).as_posix(),
                    media_type=media_type,
                    extension=path.suffix.removeprefix(".").casefold(),
                    size_bytes=stat.st_size,
                    modified_at=stat.st_mtime,
                    artwork_path=artwork_path,
                )
            )
    return tuple(sorted(entries, key=lambda entry: entry.relative_path.casefold()))
