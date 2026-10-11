from __future__ import annotations

import sys
import threading
import types
from pathlib import Path

import pytest

from qtmedia.desktop_service.download import build_download_options, download_media
from qtmedia.desktop_service.inspection import inspect_url
from qtmedia.desktop_service.models import (
    FormatOption,
    FormatSelection,
    InspectedMedia,
    MediaLibrary,
)
from qtmedia.desktop_service.policy import AdapterPolicy

YOUTUBE = "https://www.youtube.com/watch?v=abcdefghijk"


def inspect(formats):
    return inspect_url(YOUTUBE, AdapterPolicy(), extractor=lambda _url, _opts: {"title": "Song", "formats": formats})


@pytest.mark.parametrize(
    ("audio", "label"),
    [
        ({"format_id": "251", "vcodec": "none", "acodec": "opus", "abr": 160.3}, "FLAC · from Opus 160 kbps"),
        ({"format_id": "140", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 129.5}, "FLAC · from AAC 130 kbps"),
        ({"format_id": "x", "vcodec": "none", "acodec": "opus"}, "FLAC · from Opus"),
    ],
)
def test_flac_option_names_its_lossy_source(audio, label):
    inspected = inspect([audio])

    flac = [item for item in inspected.result.formats if item.extension == "flac"]
    assert [(item.kind, item.label) for item in flac] == [("audio", label)]
    assert inspected.media.selection_for(flac[0].key).extension == "flac"
    assert inspected.media.selection_for(flac[0].key).selector == audio["format_id"]
    # Music is FLAC only: no lossy MP3 re-encode is offered.
    assert not any(item.extension == "mp3" for item in inspected.result.formats)


def test_equal_heights_prefer_h264_for_compatibility():
    inspected = inspect(
        [
            {"format_id": "vp9", "ext": "mp4", "height": 1080, "vcodec": "vp09.00.40.08", "acodec": "none"},
            {"format_id": "avc", "ext": "mp4", "height": 1080, "vcodec": "avc1.640028", "acodec": "none"},
            {"format_id": "av1", "ext": "mp4", "height": 1080, "vcodec": "av01.0.08M.08", "acodec": "none"},
            {"format_id": "a", "vcodec": "none", "acodec": "opus", "abr": 160},
        ]
    )

    video = [item for item in inspected.result.formats if item.kind == "video"]
    assert inspected.media.selection_for(video[0].key).selector.startswith("avc+")


def _flac_media() -> InspectedMedia:
    return InspectedMedia(
        source_url=YOUTUBE,
        media_id="media-1",
        title="Song",
        site="YouTube",
        thumbnail_url=None,
        formats=(FormatOption("fmt-flac", "FLAC · from Opus 160 kbps", "flac", "audio"),),
        selections={"fmt-flac": FormatSelection("fmt-flac", "audio", "251", "flac")},
    )


def test_flac_downloads_convert_and_embed_the_cover(tmp_path: Path):
    library = MediaLibrary.create(tmp_path / "library")

    options = build_download_options(_flac_media(), "fmt-flac", library, lambda _event: None, threading.Event())

    keys = [pp["key"] for pp in options["postprocessors"]]
    assert keys == ["FFmpegExtractAudio", "FFmpegThumbnailsConvertor", "EmbedThumbnail"]
    assert options["postprocessors"][0]["preferredcodec"] == "flac"
    assert options["postprocessors"][1]["format"] == "jpg"
    assert options["writethumbnail"] is True


def test_mp3_downloads_use_lame_v0_and_no_artwork(tmp_path: Path):
    library = MediaLibrary.create(tmp_path / "library")
    media = InspectedMedia(
        source_url=YOUTUBE, media_id="media-1", title="Song", site="YouTube", thumbnail_url=None,
        formats=(FormatOption("fmt-mp3", "MP3 · from Opus 139 kbps", "mp3", "audio", None, None),),
        selections={"fmt-mp3": FormatSelection("fmt-mp3", "audio", "251", "mp3")},
    )

    options = build_download_options(media, "fmt-mp3", library, lambda _event: None, threading.Event())

    assert [pp["key"] for pp in options["postprocessors"]] == ["FFmpegExtractAudio"]
    assert options["postprocessors"][0]["preferredquality"] == "0"  # VBR V0, ~245 kbps
    assert "writethumbnail" not in options


def test_flac_downloads_are_saved_as_flac(monkeypatch, tmp_path: Path):
    library = MediaLibrary.create(tmp_path / "library")

    class FakeYdl:
        def __init__(self, _opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def download(self, _sources):
            (library.temp / "Song [media-1].flac").write_bytes(b"fLaC")
            return 0

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYdl))

    result = download_media(_flac_media(), "fmt-flac", library, lambda _event: None, threading.Event())

    assert result.relative_path == "audio/Song [media-1].flac"
    assert result.extension == "flac"
