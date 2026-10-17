from __future__ import annotations

import sys
import threading
import types
from pathlib import Path

import pytest

import qtmedia.desktop_service.download as desktop_download
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

    assert result.relative_path == "audio/Song.flac"
    assert result.extension == "flac"


def test_lossy_codecs_are_recognised():
    from qtmedia.desktop_service.song_tags import lossy_codec

    assert lossy_codec("opus") == "opus"
    assert lossy_codec("mp4a.40.2") == "aac"
    assert lossy_codec("vorbis") == "vorbis"
    assert lossy_codec("flac") is None
    assert lossy_codec("alac") is None
    assert lossy_codec("none") is None
    assert lossy_codec(None) is None


def test_a_flac_from_a_lossy_stream_is_tagged_with_its_source(monkeypatch, tmp_path: Path):
    library = MediaLibrary.create(tmp_path / "library")
    written: list[tuple[str, object, object]] = []

    class FakeYdl:
        def __init__(self, opts):
            self.hooks = opts["progress_hooks"]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def download(self, _sources):
            for hook in self.hooks:
                hook({"status": "downloading", "filename": "x", "downloaded_bytes": 1, "total_bytes": 2,
                      "info_dict": {"acodec": "opus", "abr": 159.8}})
            (library.temp / "Song [media-1].flac").write_bytes(b"fLaC")
            return 0

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYdl))
    monkeypatch.setattr(
        desktop_download, "write_source_tags",
        lambda path, acodec, abr: written.append((path.name, acodec, abr)) or True,
    )

    download_media(_flac_media(), "fmt-flac", library, lambda _event: None, threading.Event())

    assert written == [("Song.flac", "opus", 159.8)]


def test_write_source_tags_marks_only_flacs_from_lossy_codecs(tmp_path: Path):
    from qtmedia.desktop_service.song_tags import write_source_tags

    mp3 = tmp_path / "a.mp3"
    mp3.write_bytes(b"ID3")
    assert write_source_tags(mp3, "opus", 160) is False
    flac = tmp_path / "b.flac"
    flac.write_bytes(b"fLaC")
    assert write_source_tags(flac, "flac", None) is False


def test_source_tags_are_written_into_a_real_flac(tmp_path: Path):
    from mutagen.flac import FLAC

    from qtmedia.desktop_service.song_tags import write_source_tags

    fixture = Path(__file__).resolve().parents[2] / "QtmediaApp/src-tauri/tests/fixtures/audio/tagged.flac"
    if not fixture.is_file():
        pytest.skip("desktop audio fixtures not present")
    song = tmp_path / "Song.flac"
    song.write_bytes(fixture.read_bytes())

    assert write_source_tags(song, "mp4a.40.2", 129.5) is True

    tags = FLAC(song)
    assert tags["SOURCE_CODEC"] == ["aac"]
    assert tags["SOURCE_BITRATE"] == ["130"]
    assert tags["title"] == ["Fixture Song"]
