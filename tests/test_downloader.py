import sys
import types

from private_search.download import engine as downloader_module
from private_search.download.engine import download_video, is_direct_video_url
from private_search.net import http_client


class _FakeYDL:
    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def download(self, urls):
        for hook in self.options.get("progress_hooks", []):
            hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
        return 0


class _FakeDownloadError(Exception):
    pass


def _install_fake_yt_dlp(monkeypatch):
    fake_module = types.SimpleNamespace(
        YoutubeDL=_FakeYDL,
        utils=types.SimpleNamespace(DownloadError=_FakeDownloadError),
    )
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_module)
    return fake_module


def test_download_video_wires_custom_progress_hook_alongside_cancellation(monkeypatch):
    monkeypatch.setattr(downloader_module.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(http_client, "ytdlp_impersonate_target", lambda target: None)
    _install_fake_yt_dlp(monkeypatch)

    received = []
    download_video("https://www.xvideos.com/video123/title", progress=received.append)

    assert received == [{"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100}]


def test_download_video_sets_quiet_only_when_progress_given(monkeypatch):
    monkeypatch.setattr(downloader_module.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(http_client, "ytdlp_impersonate_target", lambda target: None)
    _install_fake_yt_dlp(monkeypatch)

    captured = {}
    original_ydl_init = _FakeYDL.__init__

    def capturing_init(self, options):
        captured.update(options)
        original_ydl_init(self, options)

    monkeypatch.setattr(_FakeYDL, "__init__", capturing_init)

    download_video("https://www.xvideos.com/video123/title")
    assert "quiet" not in captured
    assert len(captured["progress_hooks"]) == 1

    captured.clear()
    download_video("https://www.xvideos.com/video123/title", progress=lambda status: None)
    assert captured["quiet"] is True
    assert len(captured["progress_hooks"]) == 2


def test_build_ydl_options_includes_resilient_transfer_policy(monkeypatch):
    monkeypatch.delenv("PRIVATE_SEARCH_CONCURRENT_FRAGMENTS", raising=False)
    monkeypatch.delenv("PRIVATE_SEARCH_HTTP_CHUNK_SIZE", raising=False)
    monkeypatch.delenv("PRIVATE_SEARCH_DOWNLOAD_TIMEOUT", raising=False)
    monkeypatch.delenv("PRIVATE_SEARCH_DOWNLOAD_RETRIES", raising=False)
    monkeypatch.delenv("PRIVATE_SEARCH_YTDLP_JS_RUNTIME", raising=False)
    monkeypatch.delenv("PRIVATE_SEARCH_YTDLP_JS_RUNTIME_PATH", raising=False)
    monkeypatch.delenv("PRIVATE_SEARCH_YOUTUBE_PLAYER_CLIENTS", raising=False)

    options = downloader_module.build_ydl_options("https://www.xvideos.com/video123/title")

    assert options["retries"] == 5
    assert options["fragment_retries"] == 5
    assert options["socket_timeout"] == 60
    assert set(options["retry_sleep_functions"]) == {"http", "fragment", "extractor"}
    assert options["retry_sleep_functions"]["fragment"](1) == 2.0
    assert options["retry_sleep_functions"]["fragment"](3) == 6.0
    assert options["retry_sleep_functions"]["fragment"](n=3) == 6.0
    assert options["continuedl"] is True
    assert options["concurrent_fragment_downloads"] == 4
    assert options["extractor_args"] == {"youtube": {"player_client": ["web_embedded"]}}
    assert "http_chunk_size" not in options


def test_build_ydl_options_prefers_progressive_youtube_mp4(monkeypatch):
    monkeypatch.setenv("PRIVATE_SEARCH_YTDLP_JS_RUNTIME", "none")

    options = downloader_module.build_ydl_options("https://youtu.be/example")

    assert options["format"] == (
        "best[ext=mp4][protocol^=http]/best[protocol^=http]/"
        "bestvideo+bestaudio/best"
    )


def test_build_ydl_options_uses_configured_js_runtime(monkeypatch):
    monkeypatch.setenv("PRIVATE_SEARCH_YTDLP_JS_RUNTIME", "node")
    monkeypatch.delenv("PRIVATE_SEARCH_YTDLP_JS_RUNTIME_PATH", raising=False)
    monkeypatch.setenv("PRIVATE_SEARCH_YOUTUBE_PLAYER_CLIENTS", "web_embedded,default")

    options = downloader_module.build_ydl_options("https://youtu.be/example")

    assert options["js_runtimes"]["node"]["path"]
    assert options["extractor_args"] == {
        "youtube": {"player_client": ["web_embedded", "default"]}
    }


def test_build_ydl_options_allows_download_timeout_and_retry_overrides(monkeypatch):
    monkeypatch.setenv("PRIVATE_SEARCH_DOWNLOAD_TIMEOUT", "90")
    monkeypatch.setenv("PRIVATE_SEARCH_DOWNLOAD_RETRIES", "7")

    options = downloader_module.build_ydl_options("https://www.xvideos.com/video123/title")

    assert options["socket_timeout"] == 90
    assert options["retries"] == 7
    assert options["fragment_retries"] == 7


def test_build_ydl_options_caps_configured_fragment_concurrency(monkeypatch):
    monkeypatch.setenv("PRIVATE_SEARCH_CONCURRENT_FRAGMENTS", "99")

    options = downloader_module.build_ydl_options("https://www.xvideos.com/video123/title")

    assert options["concurrent_fragment_downloads"] == 8


def test_direct_url_validation():
    assert is_direct_video_url("https://www.xvideos.com/video.abc/title")
    assert not is_direct_video_url("https://www.xvideos.com/")
    assert not is_direct_video_url("https://www.xvideos.com/video...")


def test_download_video_reports_invalid_url(monkeypatch):
    assert download_video("not-a-video-url") is False


def test_direct_url_validation_shares_xhamster_creator_exclusion_with_search():
    """The downloader must reuse search.engine's SiteAdapter rules, not a stale copy."""
    assert is_direct_video_url("https://xhamster.com/videos/example-title")
    assert not is_direct_video_url("https://xhamster.com/creators/videos/example")


def test_direct_url_validation_spankbang():
    assert is_direct_video_url("https://spankbang.com/abcd/video/title")
    assert not is_direct_video_url("https://spankbang.com/")


def test_direct_url_validation_unknown_host_is_permissive():
    assert is_direct_video_url("https://example.test/some/video/path")
