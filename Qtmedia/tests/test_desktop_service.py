from __future__ import annotations

import threading
import types
from pathlib import Path

import pytest

from qtmedia.desktop_service import download as desktop_download
from qtmedia.desktop_service import inspection as desktop_inspection
from qtmedia.desktop_service.download import (
    DesktopDownloadCancelled,
    build_download_options,
    download_media,
)
from qtmedia.desktop_service.inspection import inspect_url
from qtmedia.desktop_service.models import FormatOption, InspectedMedia, MediaLibrary
from qtmedia.desktop_service.policy import AdapterPolicy, DesktopPolicyError
from qtmedia.sources.pmvhaven import PMVHavenMetadata


@pytest.mark.parametrize(
    ("url", "site"),
    [
        ("https://www.xvideos.com/video.abc/title", "XVideos"),
        ("https://xhamster.com/videos/example-title", "XHamster"),
        ("https://spankbang.com/abcd/video/title", "SpankBang"),
        ("https://www.tnaflix.com/example/title/video123", "TNAFlix"),
        ("https://www.youjizz.com/videos/example", "YouJizz"),
        ("https://www.youporn.com/watch/123/example", "YouPorn"),
        ("https://www.eporner.com/video-YRcrpiCxgtl/cum-compilation-bukkake/", "Eporner"),
        ("https://www.eporner.com/hd-porn/YRcrpiCxgtl/title/", "Eporner"),
        ("https://noodlemagazine.com/watch/-226552677_456244963", "NoodleMagazine"),
        ("https://www.noodlemagazine.com/watch/226552677_456244963", "NoodleMagazine"),
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
        "https://music.youtube.com/watch?v=r7Rn4ryE_w8",
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
        "https://music.youtube.com/playlist?list=fixture-playlist",
        "https://music.youtube.com/",
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


def test_desktop_adapter_list_is_owned_by_the_app_not_the_cli(monkeypatch):
    from qtmedia.search import engine as cli_engine

    # A site added to the CLI must not become a trusted desktop source.
    monkeypatch.setattr(
        cli_engine,
        "ADAPTERS",
        [*cli_engine.ADAPTERS, cli_engine.SiteAdapter("NewSite", "https://newsite.test/?q={query}", r"/video/")],
    )
    with pytest.raises(DesktopPolicyError):
        AdapterPolicy().validate("https://newsite.test/video/123")

    # Eporner listing pages are not video pages.
    with pytest.raises(DesktopPolicyError):
        AdapterPolicy().validate("https://www.eporner.com/cat/amateur/")

    # NoodleMagazine search and listing pages are not video pages.
    for listing in ("https://noodlemagazine.com/video/pmv", "https://noodlemagazine.com/", "https://noodlemagazine.com/watch/abc"):
        with pytest.raises(DesktopPolicyError):
            AdapterPolicy().validate(listing)


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        # SpankBang's extractor can fall back to the video ID as the title.
        ({"id": "3ikv8", "display_id": "3ikv8", "title": "3ikv8"}, "Bimbo fuck dolls pmv w names"),
        ({"id": "3ikv8", "title": None}, "Bimbo fuck dolls pmv w names"),
        ({"id": "3ikv8", "title": "A Real Title"}, "A Real Title"),
        # NoodleMagazine page titles arrive form-encoded.
        ({"id": "3ikv8", "title": "Best+pmv+teen+hot+very+hot 4k"}, "Best pmv teen hot very hot 4k"),
        # A single "+" can be part of a real title.
        ({"id": "3ikv8", "title": "Mia+Kai special"}, "Mia+Kai special"),
    ],
)
def test_inspect_titles_fall_back_to_the_url_slug_when_the_extractor_only_has_an_id(info, expected):
    inspected = inspect_url(
        "https://spankbang.com/3ikv8/video/bimbo+fuck+dolls+pmv+w+names",
        AdapterPolicy(),
        extractor=lambda _url, _options: {**info, "formats": [{"format_id": "hls-1080p", "height": 1080, "vcodec": "avc1", "acodec": "mp4a"}]},
    )

    assert inspected.result.title == expected
    assert inspected.media.title == expected


def test_inspect_keeps_untitled_media_when_neither_title_nor_slug_is_usable():
    inspected = inspect_url(
        "https://www.youporn.com/watch/123/",
        AdapterPolicy(),
        extractor=lambda _url, _options: {"id": "123", "title": "123", "formats": [{"height": 720, "vcodec": "avc1", "acodec": "mp4a"}]},
    )

    assert inspected.result.title == "123"


def test_inspect_reads_heights_from_format_ids_when_the_extractor_omits_them():
    # TNAFlix lists its HD variants with height=None and the height in the ID.
    inspected = inspect_url(
        "https://www.tnaflix.com/amateur-porn/title/video8865469",
        AdapterPolicy(),
        extractor=lambda _url, _options: {
            "title": "Example",
            "formats": [
                {"format_id": "title-720p_60fps", "height": None, "vcodec": None, "acodec": None, "ext": "mp4"},
                {"format_id": "title-480p_60fps", "height": None, "vcodec": None, "acodec": None, "ext": "mp4"},
                {"format_id": "240p", "height": 240, "vcodec": None, "acodec": None, "ext": "mp4"},
            ],
        },
    )

    video = [item for item in inspected.result.formats if item.kind == "video"]
    assert [item.height for item in video] == [720, 480, 240]
    assert inspected.media.selection_for(video[0].key).selector == "title-720p_60fps"


def test_desktop_adapters_carry_their_impersonation_profile():
    from qtmedia.desktop_service.adapters import impersonate_for_url

    assert impersonate_for_url("https://spankbang.com/3ikv8/video/title") == "chrome"
    # Some networks reset Python's TLS client on XVideos but pass curl_cffi.
    assert impersonate_for_url("https://www.xvideos.com/video.ktcpttbd7f4/title") == "chrome"
    assert impersonate_for_url("https://www.eporner.com/video-abc/title/") is None
    assert impersonate_for_url("https://www.youporn.com/watch/1/title/") is None


def test_inspect_pmvhaven_lists_the_real_hls_heights(monkeypatch):
    page = "https://pmvhaven.com/video/addiction_69074c4e2b8c34a0d339c5c5"
    master = "https://cdn.pmvhaven.test/videos/master.m3u8"
    monkeypatch.setattr(
        desktop_inspection,
        "fetch_metadata",
        lambda _url, session=None: PMVHavenMetadata(
            video_id="69074c4e2b8c34a0d339c5c5",
            title="Addiction",
            url=page,
            thumbnail_url="https://cdn.pmvhaven.test/poster.jpg",
            hls_master_url=master,
        ),
    )
    captured: list[str] = []

    def extractor(url: str, _options: dict[str, object]) -> dict[str, object]:
        captured.append(url)
        # PMVHaven's manifest declares no CODECS, so yt-dlp reports them as
        # unknown (None); each variant carries muxed audio and video.
        return {
            "title": "master",
            "formats": [
                {"format_id": "1528", "vcodec": None, "acodec": None, "height": 480, "ext": "mp4"},
                {"format_id": "5192", "vcodec": None, "acodec": None, "height": 1080, "ext": "mp4"},
            ],
        }

    inspected = inspect_url(page, AdapterPolicy(), extractor=extractor)

    assert captured == [master]
    assert inspected.result.title == "Addiction"
    assert inspected.result.site == "PMVHaven"
    video = [item for item in inspected.result.formats if item.kind == "video"]
    assert [item.height for item in video] == [1080, 480]
    assert inspected.media.download_url == master
    assert inspected.media.thumbnail_url == "https://cdn.pmvhaven.test/poster.jpg"
    # Muxed variant: no separate audio stream may be requested.
    assert inspected.media.selection_for(video[0].key).selector == "5192"
    # One best audio stream, offered only as labelled FLAC (no MP3 re-encode).
    assert [item.extension for item in inspected.result.formats if item.kind == "audio"] == ["flac"]


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
    assert [(item.kind, item.height) for item in inspected.result.formats] == [
        ("video", 1080),
        ("audio", None),
    ]
    assert "url" not in inspected.result.as_dict()


def test_inspect_url_normalizes_video_heights_and_flac_without_leaking_provider_selectors():
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
        ("audio", None, "FLAC · from Opus 160 kbps"),
    ]
    public = inspected.result.as_dict()
    assert {item["key"] for item in public["formats"]}.isdisjoint({"137", "248", "22", "251"})
    assert "137" not in str(public)
    selections = [inspected.media.selection_for(option.key) for option in inspected.result.formats]
    # Video-only streams pair with the best audio track (Opus here), else any audio.
    assert selections[0].selector == "137+251/137+bestaudio"
    assert selections[1].selector == "22"
    assert (selections[2].selector, selections[2].extension) == ("251", "flac")


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
    assert audio["postprocessors"][0]["preferredquality"] == "0"  # LAME V0
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


def test_desktop_options_use_the_host_bundled_deno(monkeypatch, tmp_path: Path):
    library = MediaLibrary.create(tmp_path / "library")
    deno = tmp_path / "deno.exe"
    deno.write_bytes(b"binary")
    monkeypatch.setenv("QTMEDIA_DENO", str(deno))
    monkeypatch.setenv("PRIVATE_SEARCH_YTDLP_JS_RUNTIME", "node")
    media = InspectedMedia(
        source_url="https://www.youtube.com/watch?v=abcdefghijk",
        media_id="media-1",
        title="Example",
        site="YouTube",
        thumbnail_url=None,
        formats=(FormatOption("audio", "Audio", "mp3"),),
    )

    download = build_download_options(media, "audio", library, lambda _event: None, threading.Event())
    inspection = desktop_inspection._desktop_ydl_options(media.source_url)

    expected = {"deno": {"path": str(deno)}}
    assert download["js_runtimes"] == expected
    assert inspection["js_runtimes"] == expected


def test_desktop_options_fall_back_to_the_configured_runtime_without_bundled_deno(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("QTMEDIA_DENO", str(tmp_path / "missing-deno.exe"))
    monkeypatch.setenv("PRIVATE_SEARCH_YTDLP_JS_RUNTIME", "none")

    options = desktop_inspection._desktop_ydl_options("https://www.youtube.com/watch?v=abcdefghijk")

    assert "js_runtimes" not in options


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
    existing = library.video / "Example_title.mp4"
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

    assert result.relative_path == "video/Example_title (2).mp4"
    assert result.artwork_path == "artwork/poster.jpg"
    assert (library.root / result.relative_path).read_bytes() == b"new media"
    assert list(library.temp.iterdir()) == []
    # The completed event doubles as a Files entry; it needs the listing fields.
    saved = (library.root / result.relative_path).stat()
    entry = result.as_dict()
    assert entry["size_bytes"] == len(b"new media")
    assert entry["modified_at"] == saved.st_mtime
    assert entry["duration_seconds"] is None


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


def test_pmvhaven_network_failures_are_reported_as_unreachable(monkeypatch):
    import requests

    def unreachable(_url, session=None):
        raise requests.exceptions.SSLError("certificate verify failed")

    monkeypatch.setattr(desktop_inspection, "fetch_metadata", unreachable)

    with pytest.raises(ValueError, match="provider_unavailable"):
        inspect_url("https://pmvhaven.com/video/addiction_69074c4e2b8c34a0d339c5c5", AdapterPolicy())


def test_unexpected_extractor_errors_mean_the_source_changed():
    from yt_dlp.utils import DownloadError, ExtractorError

    from qtmedia.desktop_service.ytdlp_errors import failure_code, is_source_changed

    broken = ExtractorError("Unable to extract player response")
    assert is_source_changed(broken)
    assert is_source_changed(DownloadError("ERROR: broken", (ExtractorError, broken, None)))
    assert failure_code(broken) == "source_changed"

    private = ExtractorError("Private video", expected=True)
    assert not is_source_changed(private)
    assert not is_source_changed(DownloadError("ERROR: private", (ExtractorError, private, None)))
    assert failure_code(OSError("offline")) == "provider_unavailable"


def test_inspection_reports_source_changed_for_extractor_breakage(monkeypatch):
    import yt_dlp
    from yt_dlp.utils import ExtractorError

    from qtmedia.desktop_service import inspection

    class Broken:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            raise ExtractorError("Unable to extract nsig function")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Broken)
    with pytest.raises(ValueError, match="source_changed"):
        inspection._extract_with_ytdlp("https://www.youtube.com/watch?v=x", {})


def test_song_tags_come_from_music_metadata_only():
    from qtmedia.desktop_service.song_tags import SongTags, song_tags

    assert song_tags(
        {"track": "Mona Lisa", "artists": ["Dominic Fike"], "album": "Sunburn", "webpage_url": "https://x.invalid"}
    ) == SongTags("Mona Lisa", "Dominic Fike", "Sunburn")
    assert song_tags({"track": "Song", "artist": "A, B"}).artist == "A, B"
    # Auto-generated YouTube music channels are "<Artist> - Topic".
    assert song_tags({"title": "Song", "channel": "Kendrick Lamar - Topic"}).artist == "Kendrick Lamar"
    assert song_tags({"title": "Clip", "uploader": "Some Channel"}) == SongTags()


def test_saved_audio_gets_title_artist_and_album_tags_and_nothing_else(tmp_path):
    import shutil
    from pathlib import Path

    from mutagen import File as MutagenFile

    from qtmedia.desktop_service.song_tags import SongTags, write_song_tags

    fixtures = Path(__file__).resolve().parents[2] / "QtmediaApp/src-tauri/tests/fixtures/audio"
    for name, saved in (("sine_16_44100.flac", "Song.flac"), ("sine_44100.mp3", "Song.mp3")):
        path = tmp_path / saved
        shutil.copy(fixtures / name, path)
        assert write_song_tags(path, SongTags(None, "Dominic Fike", "Sunburn"), "Mona Lisa")
        tags = MutagenFile(path, easy=True)
        assert tags["title"] == ["Mona Lisa"]
        assert tags["artist"] == ["Dominic Fike"]
        assert tags["album"] == ["Sunburn"]
        # Only these three are added (ffmpeg's own "encoder" tag may exist).
        assert set(tags.keys()) - {"encoder"} == {"title", "artist", "album"}
        assert not any("http" in value for values in tags.values() for value in values)

    video = tmp_path / "Clip.mp4"
    video.write_bytes(b"x")
    assert not write_song_tags(video, SongTags("a", "b", "c"), "Clip")


def test_music_takes_the_best_listening_stream_not_the_highest_number():
    from qtmedia.desktop_service.inspection import _audio_rank

    def best(*formats):
        return max(formats, key=_audio_rank)["format_id"]

    opus = {"format_id": "251", "vcodec": "none", "acodec": "opus", "abr": 121, "quality": 3}
    aac = {"format_id": "140", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 129, "quality": 3}
    drc = {"format_id": "251-drc", "vcodec": "none", "acodec": "opus", "abr": 140, "quality": 3, "format_note": "medium, DRC"}
    dub = {"format_id": "251-1", "vcodec": "none", "acodec": "opus", "abr": 140, "quality": 3, "language_preference": -1}
    orig = {"format_id": "251-0", "vcodec": "none", "acodec": "opus", "abr": 130, "quality": 3, "language_preference": 10}
    # Opus at a slightly lower bitrate still beats AAC-LC.
    assert best(aac, opus) == "251"
    # Dynamic-range-compressed variants are never chosen over the real mix.
    assert best(drc, opus) == "251"
    # The original-language track wins over a dub.
    assert best(dub, orig) == "251-0"
    # Bitrate still matters across codecs when the gap is large.
    assert best({"format_id": "low", "vcodec": "none", "acodec": "opus", "abr": 64}, {"format_id": "hi", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 256}) == "hi"
    # HE-AAC (mp4a.40.5) ranks below a similar AAC-LC stream.
    assert best({"format_id": "he", "vcodec": "none", "acodec": "mp4a.40.5", "abr": 128}, {"format_id": "lc", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 128}) == "lc"


def test_video_without_a_separate_audio_track_still_downloads():
    from qtmedia.desktop_service.inspection import _available_formats

    formats, selections = _available_formats({"formats": [
        {"format_id": "313", "ext": "webm", "vcodec": "vp9", "acodec": "none", "height": 2160},
    ]})
    video = next(option for option in formats if option.kind == "video")
    # No audio-only stream to pick: any audio the source offers (no M4A demand).
    assert selections[video.key].selector == "313+bestaudio"


@pytest.mark.parametrize(
    "url",
    [
        "https://spankbang.party/6ghm6/video/bridgette+b+pmv",
        "https://www.spankbang.party/6ghm6/video/bridgette+b+pmv",
        "https://SpankBang.Party/6ghm6/video/bridgette+b+pmv",
    ],
)
def test_desktop_policy_rewrites_spankbang_mirrors_to_the_canonical_host(url: str):
    approved = AdapterPolicy().validate(url)

    assert approved.site == "SpankBang"
    assert approved.url.startswith(("https://spankbang.com/", "https://www.spankbang.com/"))
    assert approved.url.endswith("/6ghm6/video/bridgette+b+pmv")


def test_desktop_policy_rejects_spankbang_mirror_non_video_pages():
    with pytest.raises(DesktopPolicyError, match="unsupported_source"):
        AdapterPolicy().validate("https://spankbang.party/")


def test_inspect_extracts_spankbang_mirrors_through_the_canonical_url():
    seen: list[str] = []

    def extractor(url, _options):
        seen.append(url)
        return {"title": "Fixture", "formats": [{"format_id": "hls-720", "height": 720, "vcodec": "avc1", "acodec": "mp4a", "ext": "mp4"}]}

    inspection = inspect_url(
        "https://spankbang.party/6ghm6/video/title", AdapterPolicy(), extractor=extractor
    )

    assert seen == ["https://spankbang.com/6ghm6/video/title"]
    assert inspection.media.source_url == "https://spankbang.com/6ghm6/video/title"


def _http_403():
    import io

    from yt_dlp.networking.common import Response
    from yt_dlp.networking.exceptions import HTTPError

    return HTTPError(Response(io.BytesIO(b""), "https://spankbang.com/x/video/y", {}, status=403))


def test_http_403_means_the_source_blocked_the_connection():
    from yt_dlp.utils import DownloadError, ExtractorError

    from qtmedia.desktop_service.ytdlp_errors import failure_code, is_source_blocked

    forbidden = _http_403()
    wrapped = ExtractorError("Unable to download webpage: HTTP Error 403: Forbidden", cause=forbidden)
    download_error = DownloadError("ERROR: 403", (ExtractorError, wrapped, None))

    assert is_source_blocked(download_error)
    assert failure_code(download_error) == "source_blocked"
    challenge = ExtractorError(
        "Got HTTP Error 403 caused by Cloudflare anti-bot challenge", expected=True
    )
    assert failure_code(challenge) == "source_blocked"
    assert not is_source_blocked(ExtractorError("Private video", expected=True))
    assert failure_code(OSError("offline")) == "provider_unavailable"


def test_download_reports_source_blocked_for_http_403(tmp_path: Path):
    import yt_dlp
    from yt_dlp.utils import DownloadError, ExtractorError

    wrapped = ExtractorError("HTTP Error 403: Forbidden", cause=_http_403())

    class Blocked:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def download(self, _sources):
            raise DownloadError("ERROR: 403", (ExtractorError, wrapped, None))

    library = MediaLibrary.create(tmp_path / "library")
    media = InspectedMedia(
        source_url="https://spankbang.com/6ghm6/video/title",
        media_id="media-1",
        title="Blocked",
        site="SpankBang",
        thumbnail_url=None,
        formats=(FormatOption("video", "Video", "mp4"),),
    )

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(yt_dlp, "YoutubeDL", Blocked)
        with pytest.raises(RuntimeError, match="source_blocked"):
            download_media(media, "video", library, lambda _event: None, threading.Event())


def test_clean_stem_is_the_title_made_safe():
    assert desktop_download.clean_stem("Example/title: part 2?") == "Example_title_ part 2"
    assert desktop_download.clean_stem("  ..Song..  ") == "Song"
    assert desktop_download.clean_stem("con") == "con_"
    assert desktop_download.clean_stem("COM1") == "COM1_"
    assert desktop_download.clean_stem("???") == "media"
    long = desktop_download.clean_stem("a" * 119 + " " + "b" * 10)
    assert long == "a" * 119


def test_a_title_used_by_any_saved_media_or_cover_gets_a_number(monkeypatch, tmp_path: Path):
    library = MediaLibrary.create(tmp_path / "library")
    (library.audio / "Clip.mp3").write_bytes(b"song")
    (library.artwork / "clip (2).jpg").write_bytes(b"cover of another item")
    media = InspectedMedia(
        source_url="https://www.xvideos.com/video.abc/title",
        media_id="media-7",
        title="Clip",
        site="XVideos",
        thumbnail_url=None,
        formats=(FormatOption("video", "Video", "mp4"),),
    )

    class FakeYdl:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def download(self, _sources):
            (library.temp / "Clip [media-7].mp4").write_bytes(b"video")
            return 0

    monkeypatch.setitem(__import__("sys").modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYdl))

    result = download_media(media, "video", library, lambda _event: None, threading.Event())

    # Clip is taken by a song and "clip (2)" by a cover (case-insensitive).
    assert result.relative_path == "video/Clip (3).mp4"
