import pytest

from qtmedia_bot.bot.services import yt_options
from qtmedia_bot.download import transfer


def test_bot_yt_options_enables_configured_node_runtime(monkeypatch):
    monkeypatch.setenv("PRIVATE_SEARCH_YTDLP_JS_RUNTIME", "node")
    monkeypatch.setattr(transfer.shutil, "which", lambda name: "C:/tools/node.exe")

    assert yt_options.javascript_runtime_options() == {
        "js_runtimes": {"node": {"path": "C:/tools/node.exe"}}
    }


def test_bot_yt_options_disables_runtime_when_configured_off(monkeypatch):
    monkeypatch.setenv("PRIVATE_SEARCH_YTDLP_JS_RUNTIME", "off")

    assert yt_options.javascript_runtime_options() == {}


def test_bot_yt_options_reads_browser_cookies_only_for_youtube(monkeypatch):
    monkeypatch.setenv("PRIVATE_SEARCH_YTDLP_COOKIES_FROM_BROWSER", "chrome")

    assert yt_options.browser_cookie_options("https://youtu.be/example") == {
        "cookiesfrombrowser": ("chrome", None, None, None),
        "cachedir": False,
    }
    assert yt_options.browser_cookie_options("https://example.com/video") == {}


def test_bot_yt_options_rejects_unsupported_cookie_browser():
    with pytest.raises(ValueError, match="PRIVATE_SEARCH_YTDLP_COOKIES_FROM_BROWSER"):
        yt_options.configured_cookie_browser("not-a-browser")

