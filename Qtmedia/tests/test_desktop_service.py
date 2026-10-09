from __future__ import annotations

import threading
import types
from pathlib import Path

import pytest

from qtmedia.desktop_service import download as desktop_download
from qtmedia.desktop_service.download import (
    DesktopDownloadCancelled,
    build_download_options,
    download_media,
)
from qtmedia.desktop_service.inspection import inspect_url
from qtmedia.desktop_service.models import FormatOption, InspectedMedia, MediaLibrary
from qtmedia.desktop_service.policy import AdapterPolicy, DesktopPolicyError


@pytest.mark.parametrize(
    ("url", "site"),
    [
        ("https://www.xvideos.com/video.abc/title", "XVideos"),
        ("https://xhamster.com/videos/example-title", "XHamster"),
        ("https://spankbang.com/abcd/video/title", "SpankBang"),
        ("https://www.tnaflix.com/example/title/video123", "TNAFlix"),
        ("https://www.youjizz.com/videos/example", "YouJizz"),
        ("https://www.youporn.com/watch/123/example", "YouPorn"),
        (
            "https://pmvhaven.com/video/0123456789abcdef01234567",
            "PMVHaven",
        ),
    ],
)
def test_desktop_policy_accepts_only_configured_video_pages(url: str, site: str):
    approved = AdapterPolicy().validate(url)

    assert approved.site == site
    assert approved.url == url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=fixture-video",
        "https://www.youtube.com/shorts/fixture-video",
        "https://youtu.be/fixture-video",
    ],
)
def test_desktop_policy_accepts_youtube_video_pages(url: str):
    approved = AdapterPolicy().validate(url)

    assert approved.site == "YouTube"
    assert approved.url == url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/",
        "https://www.youtube.com/watch",
        "https://www.youtube.com/playlist?list=fixture-playlist",
        "https://youtu.be/",
    ],
)
def test_desktop_policy_rejects_youtube_homepages_and_non_video_pages(url: str):
    with pytest.raises(DesktopPolicyError) as error:
        AdapterPolicy().validate(url)

    assert error.value.code == "unsupported_source"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.test/video/1",
        "https://127.0.0.1/video/1",
        "https://localhost/video/1",
        "file:///tmp/video.mp4",
        "https://www.xvideos.com/",
    ],
)
def test_desktop_policy_rejects_unknown_private_and_non_video_urls(url: str):
    with pytest.raises(DesktopPolicyError) as error:
        AdapterPolicy().validate(url)

    assert error.value.code in {"invalid_url", "unsupported_source"}


def test_inspect_url_returns_display_safe_formats_without_source_url():
    captured: list[str] = []

    def extractor(url: str, _options: dict[str, object]) -> dict[str, object]:
        captured.append(url)
        return {
            "id": "abc123",
            "title": "Example title",
            "duration": 93,
            "thumbnail": "https://images.example.test/poster.jpg",
            "formats": [
                {"vcodec": "avc1", "acodec": "none", "height": 1080},
                {"vcodec": "none", "acodec": "mp4a", "abr": 128},
            ],
        }

    inspected = inspect_url(
        "https://www.xvideos.com/video.abc/title",
        AdapterPolicy(),
        extractor=extractor,
    )

    assert captured == ["https://www.xvideos.com/video.abc/title"]
    assert inspected.result.title == "Example title"
    assert inspected.result.site == "XVideos"
    assert inspected.result.duration_seconds == 93
    assert [(item.kind, item.height) for item in inspected.result.formats] == [("video", 1080), ("audio", None)]
    assert "url" not in inspected.result.as_dict()


def test_inspect_url_normalizes_video_heights_and_mp3_without_leaking_provider_selectors():
    def extractor(_url: str, _options: dict[str, object]) -> dict[str, object]:
        return {
            "id": "fixture-media",
            "title": "Format fixture",
            "formats": [
                {"format_id": "137", "ext": "mp4", "vcodec": "avc1", "acodec": "none", "height": 1080, "tbr": 5000},
                {"format_id": "248", "ext": "webm", "vcodec": "vp9", "acodec": "none", "height": 1080, "tbr": 4500},
                {"format_id": "22", "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a", "height": 720, "tbr": 2000},
                {"format_id": "251", "ext": "webm", "vcodec": "none", "acodec": "opus", "abr": 160},
            ],
        }

    inspected = inspect_url(
        "https://www.xvideos.com/video.abc/title",
        AdapterPolicy(),
        extractor=extractor,
    )

    assert [(item.kind, item.height, item.label) for item in inspected.result.formats] == [
        ("video", 1080, "1080p MP4"),
        ("video", 720, "720p MP4"),
        ("audio", None, "MP3 · 192 kbps"),
    ]
    public = inspected.result.as_dict()
    assert {item["key"] for item in public["formats"]}.isdisjoint({"137", "248", "22", "251"})
    assert "137" not in str(public)
    selections = [inspected.media.selection_for(option.key) for option in inspected.result.formats]
    assert selections[0].selector == "137+bestaudio[ext=m4a]"
    assert selections[1].selector == "22"
    assert selections[2].selector == "251"


def test_inspect_url_classifies_extractor_failures_as_provider_unavailable(monkeypatch):
    class FakeYdl:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def extract_info(self, _url, download=False):
            assert download is False
            raise RuntimeError("network details must not escape")

    monkeypatch.setitem(__import__("sys").modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYdl))

    with pytest.raises(ValueError, match="provider_unavailable"):
        inspect_url("https://www.xvideos.com/video.abc/title", AdapterPolicy())


def test_download_options_use_temp_root_and_selected_formats(tmp_path: Path):
    library = MediaLibrary.create(tmp_path / "library")
    media = InspectedMedia(
        source_url="https://www.xvideos.com/video.abc/title",
        media_id="media-1",
        title="Example title",
        site="XVideos",
        thumbnail_url=None,
        formats=(FormatOption("video", "Video", "mp4"), FormatOption("audio", "Audio", "mp3")),
    )

    video = build_download_options(media, "video", library, lambda _event: None, threading.Event())
    audio = build_download_options(media, "audio", library, lambda _event: None, threading.Event())

    assert Path(video["paths"]["home"]) == library.temp
    assert video["merge_output_format"] == "mp4"
    assert video["format"] == "bestvideo+bestaudio/best"
    assert audio["format"] == "bestaudio/best"
    assert audio["postprocessors"][0]["preferredcodec"] == "mp3"
    assert audio["postprocessors"][0]["preferredquality"] == "192"
    assert "cookiesfrombrowser" not in audio
    # stdout is the sidecar protocol pipe; yt-dlp's console bar would corrupt it.
    assert video["noprogress"] is True
    assert audio["noprogress"] is True


def test_download_options_use_the_host_bundled_ffmpeg(monkeypatch, tmp_path: Path):
    library = MediaLibrary.create(tmp_path / "library")
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"binary")
    monkeypatch.setenv("QTMEDIA_FFMPEG", str(ffmpeg))
    media = InspectedMedia(
        source_url="https://www.xvideos.com/video.abc/title",
        media_id="media-1",
        title="Example",
        site="XVideos",
        thumbnail_url=None,
        formats=(FormatOption("audio", "Audio", "mp3"),),
    )

    options = build_download_options(media, "audio", library, lambda _event: None, threading.Event())

    assert options["ffmpeg_location"] == str(ffmpeg)


def test_download_finalizes_atomically_with_collision_safe_name(monkeypatch, tmp_path: Path):
    library = MediaLibrary.create(tmp_path / "library")
    media = InspectedMedia(
        source_url="https://www.xvideos.com/video.abc/title",
        media_id="media-1",
        title="Example/title",
        site="XVideos",
        thumbnail_url="https://images.example.test/poster.jpg",
        formats=(FormatOption("video", "Video", "mp4"),),
    )
    existing = library.video / "Example_title [media-1].mp4"
    existing.write_bytes(b"old")

    class FakeYdl:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def download(self, _sources):
            (library.temp / "Example_title [media-1].mp4").write_bytes(b"new media")
            return 0

    monkeypatch.setitem(__import__("sys").modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYdl))
    monkeypatch.setattr(desktop_download, "_download_artwork", lambda *_args: "artwork/poster.jpg")

    result = download_media(media, "video", library, lambda _event: None, threading.Event())

    assert result.relative_path == "video/Example_title [media-1] (2).mp4"
    assert result.artwork_path == "artwork/poster.jpg"
    assert (library.root / result.relative_path).read_bytes() == b"new media"
    assert list(library.temp.iterdir()) == []


def test_download_cancellation_cleans_partial_output(monkeypatch, tmp_path: Path):
    library = MediaLibrary.create(tmp_path / "library")
    media = InspectedMedia(
        source_url="https://www.xvideos.com/video.abc/title",
        media_id="media-1",
        title="Cancelled",
        site="XVideos",
        thumbnail_url=None,
        formats=(FormatOption("video", "Video", "mp4"),),
    )
    cancel = threading.Event()

    class FakeYdl:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def download(self, _sources):
            (library.temp / "Cancelled [media-1].part").write_bytes(b"partial")
            cancel.set()
            return 0

    monkeypatch.setitem(__import__("sys").modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYdl))

    with pytest.raises(DesktopDownloadCancelled):
        download_media(media, "video", library, lambda _event: None, cancel)

    assert list(library.temp.iterdir()) == []


def test_download_cancellation_wrapped_by_ytdlp_is_still_cancelled(monkeypatch, tmp_path: Path):
    library = MediaLibrary.create(tmp_path / "library")
    media = InspectedMedia(
        source_url="https://www.xvideos.com/video.abc/title",
        media_id="media-1",
        title="Cancelled",
        site="XVideos",
        thumbnail_url=None,
        formats=(FormatOption("video", "Video", "mp4"),),
    )
    cancel = threading.Event()

    class FakeYdl:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def download(self, _sources):
            # yt-dlp re-raises progress-hook exceptions as its own DownloadError.
            (library.temp / "Cancelled [media-1].part").write_bytes(b"partial")
            cancel.set()
            raise RuntimeError("ERROR: cancelled")

    monkeypatch.setitem(__import__("sys").modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYdl))

    with pytest.raises(DesktopDownloadCancelled):
        download_media(media, "video", library, lambda _event: None, cancel)

    assert list(library.temp.iterdir()) == []


def test_cancellation_survives_temp_files_still_locked_by_fragment_threads(monkeypatch, tmp_path: Path):
    library = MediaLibrary.create(tmp_path / "library")
    media = InspectedMedia(
        source_url="https://www.xvideos.com/video.abc/title",
        media_id="media-1",
        title="Cancelled",
        site="XVideos",
        thumbnail_url=None,
        formats=(FormatOption("video", "Video", "mp4"),),
    )
    cancel = threading.Event()
    locked = library.temp / "Cancelled [media-1].f620.mp4.part-Frag3.part"
    releases_after = {"attempts": 2}
    real_unlink = Path.unlink

    def unlink(self, missing_ok=False):
        # Windows refuses to delete a file another thread still has open.
        if self == locked and releases_after["attempts"] > 0:
            releases_after["attempts"] -= 1
            raise PermissionError(32, "in use")
        return real_unlink(self, missing_ok=missing_ok)

    class FakeYdl:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def download(self, _sources):
            locked.write_bytes(b"fragment")
            cancel.set()
            raise RuntimeError("ERROR: cancelled")

    monkeypatch.setitem(__import__("sys").modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYdl))
    monkeypatch.setattr(Path, "unlink", unlink)
    monkeypatch.setattr(desktop_download.time, "sleep", lambda _seconds: None)

    with pytest.raises(DesktopDownloadCancelled):
        download_media(media, "video", library, lambda _event: None, cancel)

    assert list(library.temp.iterdir()) == []


def test_library_startup_recovers_stale_temp_files(tmp_path: Path):
    root = tmp_path / "library"
    temp = root / "temp"
    temp.mkdir(parents=True)
    (temp / "stale.part").write_bytes(b"partial")
    nested = temp / "job"
    nested.mkdir()
    (nested / "fragment").write_bytes(b"partial")

    MediaLibrary.create(root)

    assert list(temp.iterdir()) == []
