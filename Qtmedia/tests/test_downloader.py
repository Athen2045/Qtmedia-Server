import sys
import types

import pytest

from qtmedia.download import engine as downloader_module
from qtmedia.download.engine import download_video, is_direct_video_url
from qtmedia.net import http_client


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

    options = downloader_module.build_ydl_options("https://www.xvideos.com/video123/title")

    assert options["retries"] == http_client.RETRY_ATTEMPTS
    assert options["fragment_retries"] == http_client.RETRY_ATTEMPTS
    assert options["socket_timeout"] == 20
    assert options["continuedl"] is True
    assert options["concurrent_fragment_downloads"] == 4
    assert "http_chunk_size" not in options


def test_build_ydl_options_caps_configured_fragment_concurrency(monkeypatch):
    monkeypatch.setenv("PRIVATE_SEARCH_CONCURRENT_FRAGMENTS", "99")

    options = downloader_module.build_ydl_options("https://www.xvideos.com/video123/title")

    assert options["concurrent_fragment_downloads"] == 8


def test_build_ydl_options_enables_configured_javascript_runtime(monkeypatch):
    monkeypatch.setenv("PRIVATE_SEARCH_YTDLP_JS_RUNTIME", "node")
    monkeypatch.setattr(
        downloader_module.shutil,
        "which",
        lambda name: r"C:\\Program Files\\nodejs\\node.exe" if name == "node" else None,
    )

    options = downloader_module.build_ydl_options("https://www.youtube.com/watch?v=example")

    assert options["js_runtimes"] == {
        "node": {"path": r"C:\\Program Files\\nodejs\\node.exe"}
    }


def test_build_ydl_options_can_force_ipv4(monkeypatch):
    monkeypatch.setenv("PRIVATE_SEARCH_YTDLP_FORCE_IPV4", "1")

    options = downloader_module.build_ydl_options("https://www.youtube.com/watch?v=example")

    assert options["source_address"] == "0.0.0.0"


def test_build_ydl_options_uses_opt_in_firefox_cookies_for_spankbang(monkeypatch):
    monkeypatch.setenv("PRIVATE_SEARCH_CLI_YTDLP_COOKIES_FROM_BROWSER", "firefox")
    monkeypatch.setenv("PRIVATE_SEARCH_CLI_YTDLP_COOKIES_BROWSER_PROFILE", "default-release")
    monkeypatch.setenv(
        "PRIVATE_SEARCH_CLI_YTDLP_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/142.0",
    )

    options = downloader_module.build_ydl_options(
        "https://spankbang.com/8acr9/video/example"
    )

    assert options["cookiesfrombrowser"] == ("firefox", "default-release", None, None)
    assert options["cachedir"] is False
    assert options["http_headers"]["User-Agent"].endswith("Firefox/142.0")


def test_build_ydl_options_does_not_use_cli_spankbang_cookies_for_other_sites(monkeypatch):
    monkeypatch.setenv("PRIVATE_SEARCH_CLI_YTDLP_COOKIES_FROM_BROWSER", "firefox")

    options = downloader_module.build_ydl_options("https://www.xvideos.com/video123/title")

    assert "cookiesfrombrowser" not in options


def test_build_ydl_options_requires_matching_user_agent_for_spankbang_cookies(monkeypatch):
    monkeypatch.setenv("PRIVATE_SEARCH_CLI_YTDLP_COOKIES_FROM_BROWSER", "firefox")
    monkeypatch.delenv("PRIVATE_SEARCH_CLI_YTDLP_USER_AGENT", raising=False)

    with pytest.raises(ValueError, match="PRIVATE_SEARCH_CLI_YTDLP_USER_AGENT"):
        downloader_module.build_ydl_options("https://spankbang.com/8acr9/video/example")


def test_build_ydl_options_does_not_apply_global_impersonation_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr(
        http_client,
        "ytdlp_impersonate_target",
        lambda profile: calls.append(profile) or "chrome-131",
    )

    options = downloader_module.build_ydl_options("https://www.youtube.com/watch?v=example")

    assert calls == []
    assert "impersonate" not in options


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

