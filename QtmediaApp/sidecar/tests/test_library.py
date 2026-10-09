from __future__ import annotations

from pathlib import Path

import pytest

from qtmedia_engine.library import LibraryError, confined_path, scan_library


def test_scan_library_returns_only_audio_and_video(tmp_path: Path):
    root = tmp_path / "library"
    (root / "audio").mkdir(parents=True)
    (root / "video").mkdir()
    (root / "artwork").mkdir()
    (root / "temp").mkdir()
    (root / "audio" / "song.mp3").write_bytes(b"audio")
    (root / "video" / "clip.mp4").write_bytes(b"video")
    (root / "artwork" / "song.jpg").write_bytes(b"image")
    (root / "temp" / "partial.part").write_bytes(b"partial")

    entries = scan_library(root)

    assert [entry.relative_path for entry in entries] == [
        "audio/song.mp3",
        "video/clip.mp4",
    ]
    assert [entry.media_type for entry in entries] == ["audio", "video"]
    assert entries[0].artwork_path == "artwork/song.jpg"


@pytest.mark.parametrize("relative", ["../escape.mp4", "/absolute.mp4", "C:/escape.mp4"])
def test_confined_path_rejects_paths_outside_library(tmp_path: Path, relative: str):
    root = tmp_path / "library"
    root.mkdir()

    with pytest.raises(LibraryError, match="path_escape"):
        confined_path(root, relative)
