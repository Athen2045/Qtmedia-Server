"""Local image discovery for SmartImage folder selection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SUPPORTED_IMAGE_SUFFIXES = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}
)


@dataclass(frozen=True)
class ImageCandidate:
    path: Path
    relative_path: str


def discover_images(root: Path) -> list[ImageCandidate]:
    root = root.resolve()
    if not root.exists():
        return []

    candidates: list[ImageCandidate] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in SUPPORTED_IMAGE_SUFFIXES:
            continue
        resolved = path.resolve()
        relative_path = resolved.relative_to(root).as_posix()
        candidates.append(
            ImageCandidate(path=resolved, relative_path=relative_path)
        )

    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.relative_path.casefold(),
            candidate.relative_path,
        ),
    )
