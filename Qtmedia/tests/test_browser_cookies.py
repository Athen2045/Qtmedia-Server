from __future__ import annotations

import os
from pathlib import Path

import pytest

from qtmedia.desktop_service import browser_cookies
from qtmedia.desktop_service.browser_cookies import (
    active_firefox_profile,
    site_ydl_options,
)

SPANKBANG = "https://spankbang.com/6ghm6/video/title"


def _profile(root: Path, name: str, version: str, modified: float) -> Path:
    profile = root / name
    profile.mkdir(parents=True)
    (profile / "compatibility.ini").write_text(
        f"[Compatibility]\nLastVersion={version}_20261005135250/20261005135250\n", encoding="utf-8"
    )
    cookies = profile / "cookies.sqlite"
    cookies.write_bytes(b"")
    os.utime(cookies, (modified, modified))
    return profile


@pytest.fixture
def firefox_root(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "Mozilla" / "Firefox" / "Profiles"
    root.mkdir(parents=True)
    monkeypatch.setattr(browser_cookies, "_profiles_root", lambda: root)
    return root


def test_the_most_recently_used_profile_supplies_cookies_and_user_agent(firefox_root: Path):
    _profile(firefox_root, "old.default", "140.0.2", 1_000)
    current = _profile(firefox_root, "new.default-release", "157.0.1", 2_000)

    profile = active_firefox_profile()

    assert profile is not None
    assert profile.path == current
    assert profile.user_agent == (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:157.0) Gecko/20100101 Firefox/157.0"
    )


def test_no_profile_without_cookies_or_a_version(firefox_root: Path):
    assert active_firefox_profile() is None
    (firefox_root / "empty").mkdir()
    (firefox_root / "empty" / "cookies.sqlite").write_bytes(b"")
    assert active_firefox_profile() is None


def test_cookie_mode_off_keeps_plain_impersonation(firefox_root: Path, monkeypatch):
    monkeypatch.delenv(browser_cookies.COOKIES_ENV, raising=False)
    _profile(firefox_root, "p.default-release", "157.0.1", 2_000)

    options = site_ydl_options(SPANKBANG)

    assert "cookiesfrombrowser" not in options
    assert "http_headers" not in options
    assert options["impersonate"].client == "chrome"


def test_cookie_mode_sends_firefox_cookies_user_agent_and_fingerprint_to_spankbang(
    firefox_root: Path, monkeypatch
):
    monkeypatch.setenv(browser_cookies.COOKIES_ENV, "firefox")
    profile = _profile(firefox_root, "p.default-release", "157.0.1", 2_000)

    options = site_ydl_options(SPANKBANG)

    assert options["cookiesfrombrowser"] == ("firefox", str(profile), None, None)
    assert options["http_headers"] == {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:157.0) Gecko/20100101 Firefox/157.0"
    }
    assert options["cachedir"] is False
    assert options["impersonate"].client == "firefox"


@pytest.mark.parametrize(
    "url",
    ["https://www.xvideos.com/video.abc/title", "https://noodlemagazine.com/watch/-1_2", "https://example.test/x"],
)
def test_cookie_mode_never_reaches_sites_without_the_flag(url: str, firefox_root: Path, monkeypatch):
    monkeypatch.setenv(browser_cookies.COOKIES_ENV, "firefox")
    _profile(firefox_root, "p.default-release", "157.0.1", 2_000)

    options = site_ydl_options(url)

    assert "cookiesfrombrowser" not in options
    assert "http_headers" not in options


def test_cookie_mode_without_a_readable_profile_is_a_stable_error(firefox_root: Path, monkeypatch):
    monkeypatch.setenv(browser_cookies.COOKIES_ENV, "firefox")

    with pytest.raises(ValueError, match="cookies_unavailable"):
        site_ydl_options(SPANKBANG)


def test_unknown_browsers_are_ignored(monkeypatch):
    monkeypatch.setenv(browser_cookies.COOKIES_ENV, "chrome")
    assert browser_cookies.configured_browser() is None
