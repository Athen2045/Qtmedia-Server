import sys
import types

import pytest

from qtmedia_bot.bot.config import BotSettings
from qtmedia_bot.bot.services import inspection
from qtmedia_bot.bot.services.inspection import InspectionError, inspect_source
from qtmedia_bot.bot.services.source_policy import SourcePolicyError
from qtmedia_bot.sources.pmvhaven import PMVHavenMetadata


def settings(**overrides):
    values = {
        "token": "test-token",
        "base_url": "https://api.example/bot",
        "file_base_url": "https://api.example/file/bot",
        "local_mode": False,
        "private_chats_only": True,
        "allowed_user_ids": frozenset({123}),
        "allowed_domains": frozenset({"example.com"}),
        "max_upload_bytes": 4_000_000,
        "max_duration_seconds": 120,
    }
    values.update(overrides)
    return BotSettings(**values)


def install_fake_ytdlp(monkeypatch, info):
    seen = {}

    class FakeYDL:
        def __init__(self, options):
            seen["options"] = options

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            seen["url"] = url
            seen["download"] = download
            return info

    fake_module = types.SimpleNamespace(
        YoutubeDL=FakeYDL,
        utils=types.SimpleNamespace(DownloadError=RuntimeError),
    )
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_module)
    return seen


def test_inspection_uses_metadata_only_and_does_not_use_cli_cache(monkeypatch, capsys):
    monkeypatch.setattr(inspection, "validate_source_url", lambda *args: None)
    monkeypatch.setattr(
        inspection.http_client, "ytdlp_impersonate_target", lambda profile=None: None
    )
    monkeypatch.setattr(
        inspection,
        "javascript_runtime_options",
        lambda: {"js_runtimes": {"node": {"path": "node"}}},
    )
    monkeypatch.setattr(
        inspection,
        "browser_cookie_options",
        lambda url: {"cookiesfrombrowser": ("chrome", None, None, None)},
    )
    seen = install_fake_ytdlp(
        monkeypatch,
        {
            "title": "Example title",
            "duration": 60,
            "formats": [{"format_id": "720", "height": 720}],
        },
    )

    result = inspect_source("https://example.com/video", settings())

    assert result.title == "Example title"
    assert result.duration_seconds == 60
    assert result.formats == ({"format_id": "720", "height": 720},)
    assert seen["download"] is False
    assert seen["options"]["skip_download"] is True
    assert seen["options"]["noplaylist"] is True
    assert seen["options"]["js_runtimes"] == {"node": {"path": "node"}}
    assert seen["options"]["cookiesfrombrowser"] == ("chrome", None, None, None)
    seen["options"]["logger"].error("private provider identifier")
    assert capsys.readouterr().out == ""
    assert capsys.readouterr().err == ""


def test_inspection_rejects_playlists_and_duration_over_limit(monkeypatch):
    monkeypatch.setattr(inspection, "validate_source_url", lambda *args: None)
    monkeypatch.setattr(
        inspection.http_client, "ytdlp_impersonate_target", lambda profile=None: None
    )
    install_fake_ytdlp(monkeypatch, {"entries": [{"id": "one"}]})

    with pytest.raises(InspectionError, match="(?i)playlist"):
        inspect_source("https://example.com/playlist", settings())

    install_fake_ytdlp(monkeypatch, {"title": "Long", "duration": 121, "formats": []})
    with pytest.raises(InspectionError, match="duration"):
        inspect_source("https://example.com/long", settings())


def test_inspection_does_not_apply_global_impersonation_to_unconfigured_host(
    monkeypatch,
):
    profiles = []
    monkeypatch.setattr(inspection, "validate_source_url", lambda *args: None)
    monkeypatch.setattr(
        inspection.http_client,
        "ytdlp_impersonate_target",
        lambda profile=None: profiles.append(profile) or "chrome-131",
    )
    install_fake_ytdlp(monkeypatch, {"title": "Example", "formats": []})

    inspect_source("https://youtube.com/watch?v=example", settings())

    assert profiles == []


def test_eporner_inspection_tries_provider_embed_after_extractor_failure(monkeypatch):
    calls = []
    source_url = "https://www.eporner.com/video-AbC123/example-title"
    embed_url = "https://www.eporner.com/embed/AbC123"

    monkeypatch.setattr(inspection, "validate_source_url", lambda *args: None)
    monkeypatch.setattr(
        inspection.http_client, "ytdlp_impersonate_target", lambda profile=None: None
    )

    class FakeYDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            calls.append((url, self.options.get("force_generic_extractor", False)))
            if url == source_url and not self.options.get("force_generic_extractor"):
                raise RuntimeError("hash changed")
            return {
                "title": "Example Eporner video",
                "duration": 60,
                "formats": [{"format_id": "720", "height": 720}],
            }

    fake_module = types.SimpleNamespace(
        YoutubeDL=FakeYDL,
        utils=types.SimpleNamespace(DownloadError=RuntimeError),
    )
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_module)

    result = inspect_source(
        source_url,
        settings(allowed_domains=frozenset({"eporner.com"})),
    )

    assert result.download_url == embed_url
    assert calls == [(source_url, False), (embed_url, False)]


def test_noodle_extractor_match_failure_is_handled_as_a_fallback(monkeypatch):
    calls = []
    source_url = "https://noodlemagazine.com/watch/-123_456"

    monkeypatch.setattr(inspection, "validate_source_url", lambda *args: None)
    monkeypatch.setattr(
        inspection.http_client, "ytdlp_impersonate_target", lambda profile=None: None
    )

    class FakeYDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            calls.append((url, self.options.get("force_generic_extractor", False)))
            if not self.options.get("force_generic_extractor"):
                raise AttributeError("NoneType has no attribute group")
            return {
                "title": "Example NoodleMagazine video",
                "duration": 60,
                "formats": [{"format_id": "720", "height": 720}],
            }

    fake_module = types.SimpleNamespace(
        YoutubeDL=FakeYDL,
        utils=types.SimpleNamespace(DownloadError=RuntimeError),
    )
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_module)

    result = inspect_source(
        source_url,
        settings(allowed_domains=frozenset({"noodlemagazine.com"})),
    )

    assert result.download_url is None
    assert calls == [
        (source_url, False),
        ("https://adult.noodlemagazine.com/watch/-123_456", False),
        ("https://www.noodlemagazine.com/watch/-123_456", False),
        (source_url, True),
    ]


def test_noodle_adapter_scopes_browser_impersonation_to_bot_inspection(monkeypatch):
    profiles = []
    monkeypatch.setattr(inspection, "validate_source_url", lambda *args: None)
    monkeypatch.setattr(
        inspection.http_client,
        "ytdlp_impersonate_target",
        lambda profile=None: profiles.append(profile) or None,
    )
    install_fake_ytdlp(
        monkeypatch,
        {"title": "Example", "formats": [{"format_id": "720", "height": 720}]},
    )

    inspect_source(
        "https://noodlemagazine.com/watch/-123_456",
        settings(allowed_domains=frozenset({"noodlemagazine.com"})),
    )

    assert profiles == ["chrome131"]


def test_inspection_records_exact_allowed_direct_candidate_from_metadata(monkeypatch):
    validated = []
    monkeypatch.setattr(
        inspection,
        "validate_source_url",
        lambda url, domains: validated.append((url, domains)),
    )
    monkeypatch.setattr(
        inspection.http_client,
        "ytdlp_impersonate_target",
        lambda profile=None: None,
    )
    install_fake_ytdlp(
        monkeypatch,
        {
            "title": "Example",
            "formats": [],
            "url": "https://example.com/media.mp4",
        },
    )
    monkeypatch.setattr(
        inspection,
        "probe_exact_video_size",
        lambda url: 1_500_000,
        raising=False,
    )

    result = inspect_source("https://example.com/video", settings())

    assert result.best_available is not None
    assert result.best_available.url == "https://example.com/media.mp4"
    assert result.best_available.size_bytes == 1_500_000
    assert result.best_available.validation_domains == frozenset({"example.com"})
    assert validated == [
        ("https://example.com/video", frozenset({"example.com"})),
        ("https://example.com/media.mp4", frozenset({"example.com"})),
    ]


def test_pmvhaven_inspection_resolves_adapter_media_before_ytdlp(monkeypatch):
    source_url = "https://pmvhaven.com/video/example_0123456789abcdef01234567"
    media_url = (
        "https://pmvhavencloud.s3.eu-west-par.io.cloud.ovh.net/media/master.m3u8"
    )
    direct_url = "https://pmvhavencloud.s3.eu-west-par.io.cloud.ovh.net/media/video.mp4"
    validated = []
    monkeypatch.setattr(
        inspection,
        "validate_source_url",
        lambda url, domains: validated.append((url, domains)),
    )
    monkeypatch.setattr(
        inspection,
        "fetch_metadata",
        lambda url: PMVHavenMetadata(
            video_id="0123456789abcdef01234567",
            title="Provider title",
            url=source_url,
            video_url=direct_url,
            hls_master_url=media_url,
        ),
        raising=False,
    )
    monkeypatch.setattr(
        inspection,
        "probe_exact_video_size",
        lambda url: 1_500_000 if url == direct_url else None,
    )
    monkeypatch.setattr(
        inspection.http_client,
        "ytdlp_impersonate_target",
        lambda profile=None: None,
    )
    seen = install_fake_ytdlp(
        monkeypatch,
        {
            "title": "Manifest title",
            "duration": 60,
            "formats": [{"format_id": "720", "height": 720}],
        },
    )

    result = inspect_source(
        source_url,
        settings(allowed_domains=frozenset({"pmvhaven.com"})),
    )

    assert seen["url"] == media_url
    assert result.url == source_url
    assert result.download_url == media_url
    assert result.best_available is not None
    assert result.best_available.url == direct_url
    assert result.best_available.size_bytes == 1_500_000
    assert result.best_available.validation_domains == frozenset(
        {"pmvhavencloud.s3.eu-west-par.io.cloud.ovh.net"}
    )
    assert result.title == "Provider title"
    assert validated == [
        (source_url, frozenset({"pmvhaven.com"})),
        (
            media_url,
            frozenset({"pmvhavencloud.s3.eu-west-par.io.cloud.ovh.net"}),
        ),
        (
            direct_url,
            frozenset({"pmvhavencloud.s3.eu-west-par.io.cloud.ovh.net"}),
        ),
    ]


def test_exact_video_size_requires_non_redirecting_video_with_known_length(
    monkeypatch,
):
    class Response:
        def __init__(self):
            self.status_code = 200
            self.headers = {
                "Content-Type": "video/mp4",
                "Content-Length": "1500000",
            }

    monkeypatch.setattr(inspection.requests, "head", lambda *args, **kwargs: Response())

    assert (
        inspection.probe_exact_video_size("https://media.example/video.mp4")
        == 1_500_000
    )


def test_exact_video_size_rejects_redirect_unknown_length_and_non_video(monkeypatch):
    class Response:
        def __init__(self, status_code, headers):
            self.status_code = status_code
            self.headers = headers

    responses = iter(
        (
            Response(302, {"Content-Type": "video/mp4", "Content-Length": "10"}),
            Response(200, {"Content-Type": "video/mp4"}),
            Response(200, {"Content-Type": "text/html", "Content-Length": "10"}),
        )
    )
    monkeypatch.setattr(
        inspection.requests,
        "head",
        lambda *args, **kwargs: next(responses),
    )

    assert inspection.probe_exact_video_size("https://media.example/redirect") is None
    assert inspection.probe_exact_video_size("https://media.example/unknown") is None
    assert inspection.probe_exact_video_size("https://media.example/page") is None


def test_pmvhaven_inspection_rejects_adapter_media_that_fails_policy(monkeypatch):
    source_url = "https://pmvhaven.com/video/example_0123456789abcdef01234567"
    unsafe_media_url = "https://127.0.0.1/private/master.m3u8"

    def validate(url, domains):
        del domains
        if url == unsafe_media_url:
            raise SourcePolicyError("private_network", "restricted")

    monkeypatch.setattr(inspection, "validate_source_url", validate)
    monkeypatch.setattr(
        inspection,
        "fetch_metadata",
        lambda url: PMVHavenMetadata(
            video_id="0123456789abcdef01234567",
            title="Provider title",
            url=source_url,
            hls_master_url=unsafe_media_url,
        ),
        raising=False,
    )

    with pytest.raises(InspectionError) as caught:
        inspect_source(
            source_url,
            settings(allowed_domains=frozenset({"pmvhaven.com"})),
        )

    assert caught.value.code == "provider_media_rejected"

