import sys
import types

from private_search import downloader as downloader_module
from private_search import http_client
from private_search.downloader import download_video, is_direct_video_url


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


def test_direct_url_validation():
    assert is_direct_video_url("https://www.xvideos.com/video.abc/title")
    assert not is_direct_video_url("https://www.xvideos.com/")
    assert not is_direct_video_url("https://www.xvideos.com/video...")


def test_direct_url_validation_shares_xhamster_creator_exclusion_with_search():
    """downloader.py must reuse search.py's SiteAdapter rules, not a stale copy."""
    assert is_direct_video_url("https://xhamster.com/videos/example-title")
    assert not is_direct_video_url("https://xhamster.com/creators/videos/example")


def test_direct_url_validation_spankbang():
    assert is_direct_video_url("https://spankbang.com/abcd/video/title")
    assert not is_direct_video_url("https://spankbang.com/")


def test_direct_url_validation_unknown_host_is_permissive():
    assert is_direct_video_url("https://example.test/some/video/path")
