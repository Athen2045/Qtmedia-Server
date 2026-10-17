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


def test_scan_lists_flac_as_audio(tmp_path: Path):
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "Song [media-1].flac").write_bytes(b"fLaC")
    (tmp_path / "artwork").mkdir()
    (tmp_path / "artwork" / "Song [media-1].jpg").write_bytes(b"jpg")

    [entry] = scan_library(tmp_path)

    assert (entry.relative_path, entry.media_type, entry.extension) == ("audio/Song [media-1].flac", "audio", "flac")
    assert entry.artwork_path == "artwork/Song [media-1].jpg"


def test_scan_lists_mkv_mov_webm_m4v_and_avi_videos(tmp_path):
    from qtmedia_engine.library import scan_library

    for folder in ("audio", "video", "artwork"):
        (tmp_path / folder).mkdir(exist_ok=True)
    for name in ("Film.mkv", "Clip.MOV", "Talk.webm", "Show.m4v", "Old.avi", "Notes.txt"):
        (tmp_path / "video" / name).write_bytes(b"x")
    (tmp_path / "audio" / "Film.mkv").write_bytes(b"x")  # wrong folder: ignored

    entries = {entry.relative_path: entry for entry in scan_library(tmp_path)}
    assert set(entries) == {"video/Film.mkv", "video/Clip.MOV", "video/Talk.webm", "video/Show.m4v", "video/Old.avi"}
    assert entries["video/Clip.MOV"].extension == "mov"
    assert all(entry.media_type == "video" for entry in entries.values())


def test_scan_picks_artwork_in_extension_order_and_keeps_file_details(tmp_path: Path):
    for folder in ("audio", "video", "artwork"):
        (tmp_path / folder).mkdir()
    (tmp_path / "audio" / "Song.flac").write_bytes(b"fLaC-data")
    (tmp_path / "video" / "Clip.mp4").write_bytes(b"x")
    (tmp_path / "video" / "Bare.mp4").write_bytes(b"x")
    (tmp_path / "artwork" / "Song.png").write_bytes(b"png")
    (tmp_path / "artwork" / "Song.jpg").write_bytes(b"jpg")
    (tmp_path / "artwork" / "Clip.webp").write_bytes(b"webp")
    (tmp_path / "artwork" / "Clip.webp.txt").write_bytes(b"not art")

    entries = {entry.relative_path: entry for entry in scan_library(tmp_path)}

    assert entries["audio/Song.flac"].artwork_path == "artwork/Song.jpg"
    assert entries["video/Clip.mp4"].artwork_path == "artwork/Clip.webp"
    assert entries["video/Bare.mp4"].artwork_path is None
    song = entries["audio/Song.flac"]
    stat = (tmp_path / "audio" / "Song.flac").stat()
    assert (song.size_bytes, song.modified_at) == (stat.st_size, stat.st_mtime)


def test_scan_without_artwork_folder(tmp_path: Path):
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "Song.mp3").write_bytes(b"x")

    [entry] = scan_library(tmp_path)

    assert entry.artwork_path is None
