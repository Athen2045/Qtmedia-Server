import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from qtmedia_bot.bot.config import BotSettings
from qtmedia_bot.bot.services import downloads as download_service
from qtmedia_bot.bot.services.inspection import MediaInspection
from qtmedia_bot.bot.services.jobs import JobCatalog
from qtmedia_bot.bot.services.quality import QualityOption


def option(media_type="video"):
    return QualityOption(
        key="v720" if media_type == "video" else "mp3",
        label="720p" if media_type == "video" else "MP3",
        height=720 if media_type == "video" else None,
        size_bytes=4,
        size_approximate=False,
        format_selector="720" if media_type == "video" else "bestaudio",
        media_type=media_type,
    )


def best_option(size_bytes=4):
    return QualityOption(
        key="best",
        label="Best available",
        height=None,
        size_bytes=size_bytes,
        size_approximate=False,
        format_selector="bestvideo+bestaudio/best",
        media_type="video",
    )


def settings(
    job_root: Path,
    max_upload_bytes=10,
    allowed_domains=frozenset({"example.com"}),
):
    return BotSettings(
        token="test-token",
        base_url="https://api.example/bot",
        file_base_url="https://api.example/file/bot",
        local_mode=False,
        private_chats_only=True,
        allowed_user_ids=frozenset({123}),
        allowed_domains=allowed_domains,
        max_upload_bytes=max_upload_bytes,
        job_root=job_root,
        disk_reserve_bytes=1,
        download_timeout_seconds=60,
    )


def record(catalog, selected_option):
    inspection = MediaInspection(
        url="https://example.com/private-source",
        title="Private title",
        duration_seconds=30,
        formats=(),
    )
    job_id = catalog.create(123, 456, inspection, (selected_option,))
    return catalog.claim_for_user(job_id, 123, 456, selected_option.key)


def test_download_media_uses_job_directory_and_returns_path(
    monkeypatch, tmp_path, capsys
):
    import yt_dlp

    captured = {}
    validated = []

    class FakeYoutubeDL:
        def __init__(self, options):
            captured.update(options)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def download(self, urls):
            assert urls == ["https://example.com/private-source"]
            output_dir = Path(captured["outtmpl"]).parent
            (output_dir / "media.mp4").write_bytes(b"media")
            return 0

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(
        download_service,
        "validate_source_url",
        lambda url, domains: validated.append((url, domains)),
    )
    monkeypatch.setattr(
        download_service,
        "javascript_runtime_options",
        lambda: {"js_runtimes": {"node": {"path": "node"}}},
    )
    monkeypatch.setattr(
        download_service,
        "browser_cookie_options",
        lambda url: {"cookiesfrombrowser": ("chrome", None, None, None)},
    )
    catalog = JobCatalog()
    selected = record(catalog, option())

    result = download_service.download_media(
        selected, option(), settings(tmp_path), threading.Event()
    )

    assert result.path == tmp_path / selected.job_id / "media.mp4"
    assert result.media_type == "video"
    assert captured["format"] == "720"
    assert captured["max_filesize"] == 10
    assert captured["js_runtimes"] == {"node": {"path": "node"}}
    assert captured["cookiesfrombrowser"] == ("chrome", None, None, None)
    captured["logger"].error("private provider identifier")
    assert capsys.readouterr().out == ""
    assert capsys.readouterr().err == ""


def test_download_media_deletes_job_directory_when_output_exceeds_cap(
    monkeypatch, tmp_path
):
    import yt_dlp

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def download(self, urls):
            output_dir = Path(self.options["outtmpl"]).parent
            (output_dir / "too-large.mp4").write_bytes(b"01234567890")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(download_service, "validate_source_url", lambda *args: None)
    catalog = JobCatalog()
    selected = record(catalog, option())

    with pytest.raises(download_service.DownloadError, match="output_limit"):
        download_service.download_media(
            selected,
            option(),
            settings(tmp_path, max_upload_bytes=10),
            threading.Event(),
        )

    assert not (tmp_path / selected.job_id).exists()


def test_download_media_honors_cancellation_before_network_work(monkeypatch, tmp_path):
    import yt_dlp

    class UnexpectedYoutubeDL:
        def __init__(self, options):
            raise AssertionError("yt-dlp should not start after cancellation")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", UnexpectedYoutubeDL)
    catalog = JobCatalog()
    selected = record(catalog, option())
    cancelled = threading.Event()
    cancelled.set()

    with pytest.raises(download_service.DownloadCancelled):
        download_service.download_media(
            selected, option(), settings(tmp_path), cancelled
        )

    assert not (tmp_path / selected.job_id).exists()


def test_audio_download_returns_the_mp3_postprocessed_output(monkeypatch, tmp_path):
    import yt_dlp

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def download(self, urls):
            output_dir = Path(self.options["outtmpl"]).parent
            (output_dir / "source.m4a").write_bytes(b"0123456789")
            (output_dir / "source.mp3").write_bytes(b"mp3")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(download_service, "validate_source_url", lambda *args: None)
    catalog = JobCatalog()
    selected = record(catalog, option("audio"))

    result = download_service.download_media(
        selected,
        option("audio"),
        settings(tmp_path, max_upload_bytes=20),
        threading.Event(),
    )

    assert result.path.suffix == ".mp3"


@pytest.mark.parametrize(
    ("audio_format", "media_type", "codec", "preferredquality"),
    [
        ("mp3", "audio", "mp3", "192"),
        ("m4a", "audio", "m4a", "256"),
        ("flac", "document", "flac", None),
        ("alac", "document", "alac", None),
    ],
)
def test_audio_download_uses_requested_output_format(
    monkeypatch,
    tmp_path,
    audio_format,
    media_type,
    codec,
    preferredquality,
):
    import yt_dlp

    captured = {}

    class FakeYoutubeDL:
        def __init__(self, options):
            captured.update(options)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def download(self, urls):
            del urls
            output_dir = Path(captured["outtmpl"]).parent
            output_suffix = ".m4a" if audio_format == "alac" else f".{audio_format}"
            (output_dir / f"source{output_suffix}").write_bytes(b"audio")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(download_service, "validate_source_url", lambda *args: None)
    catalog = JobCatalog()
    selected = record(
        catalog,
        QualityOption(
            key=audio_format,
            label=audio_format.upper(),
            height=None,
            size_bytes=4,
            size_approximate=False,
            format_selector="bestaudio",
            media_type=media_type,
            audio_format=audio_format,
        ),
    )
    selected_option = selected.options[0]

    result = download_service.download_media(
        selected,
        selected_option,
        settings(tmp_path, max_upload_bytes=20),
        threading.Event(),
    )

    assert result.path.suffix == (".m4a" if audio_format == "alac" else f".{audio_format}")
    postprocessor = captured["postprocessors"][0]
    assert postprocessor["preferredcodec"] == codec
    assert postprocessor.get("preferredquality") == preferredquality


def test_download_media_uses_validated_pmvhaven_adapter_url(monkeypatch, tmp_path):
    import yt_dlp

    source_url = "https://pmvhaven.com/video/example_0123456789abcdef01234567"
    media_url = (
        "https://pmvhavencloud.s3.eu-west-par.io.cloud.ovh.net/media/master.m3u8"
    )
    validated = []
    captured = {}

    class FakeYoutubeDL:
        def __init__(self, options):
            captured.update(options)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def download(self, urls):
            assert urls == [media_url]
            output_dir = Path(captured["outtmpl"]).parent
            (output_dir / "media.mp4").write_bytes(b"media")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(
        download_service,
        "validate_source_url",
        lambda url, domains: validated.append((url, domains)),
    )
    record_with_adapter_url = SimpleNamespace(
        job_id="pmv-job",
        inspection=SimpleNamespace(
            url=source_url,
            download_url=media_url,
        ),
    )
    runtime_settings = settings(
        tmp_path,
        allowed_domains=frozenset({"pmvhaven.com"}),
    )

    result = download_service.download_media(
        record_with_adapter_url,
        option(),
        runtime_settings,
        threading.Event(),
    )

    assert result.path == tmp_path / "pmv-job" / "media.mp4"
    assert validated == [
        (source_url, frozenset({"pmvhaven.com"})),
        (
            media_url,
            frozenset({"pmvhavencloud.s3.eu-west-par.io.cloud.ovh.net"}),
        ),
    ]


def test_download_media_routes_best_fallback_to_validated_direct_url(
    monkeypatch, tmp_path
):
    import yt_dlp

    source_url = "https://pmvhaven.com/video/example_0123456789abcdef01234567"
    manifest_url = (
        "https://pmvhavencloud.s3.eu-west-par.io.cloud.ovh.net/media/master.m3u8"
    )
    direct_url = "https://pmvhavencloud.s3.eu-west-par.io.cloud.ovh.net/media/video.mp4"
    captured = {}
    validated = []

    class FakeYoutubeDL:
        def __init__(self, options):
            captured.update(options)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def download(self, urls):
            captured["urls"] = urls
            output_dir = Path(captured["outtmpl"]).parent
            (output_dir / "media.mp4").write_bytes(b"media")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(
        download_service,
        "probe_exact_video_size",
        lambda url: 4,
        raising=False,
    )
    monkeypatch.setattr(
        download_service,
        "validate_source_url",
        lambda url, domains: validated.append((url, domains)),
    )
    record_with_fallback = SimpleNamespace(
        job_id="pmv-best-job",
        inspection=SimpleNamespace(
            url=source_url,
            download_url=manifest_url,
            best_available=SimpleNamespace(
                url=direct_url,
                size_bytes=4,
                validation_domains=frozenset(
                    {"pmvhavencloud.s3.eu-west-par.io.cloud.ovh.net"}
                ),
            ),
        ),
    )
    selected_best = best_option()

    result = download_service.download_media(
        record_with_fallback,
        selected_best,
        settings(
            tmp_path,
            allowed_domains=frozenset({"pmvhaven.com"}),
        ),
        threading.Event(),
    )

    assert result.path == tmp_path / "pmv-best-job" / "media.mp4"
    assert captured["urls"] == [direct_url]
    assert captured["format"] == "bestvideo+bestaudio/best"
    assert validated == [
        (source_url, frozenset({"pmvhaven.com"})),
        (
            direct_url,
            frozenset({"pmvhavencloud.s3.eu-west-par.io.cloud.ovh.net"}),
        ),
    ]


def test_download_media_routes_generic_best_candidate_with_normal_policy(
    monkeypatch, tmp_path
):
    import yt_dlp

    captured = {}
    validated = []

    class FakeYoutubeDL:
        def __init__(self, options):
            captured.update(options)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def download(self, urls):
            captured["urls"] = urls
            output_dir = Path(captured["outtmpl"]).parent
            (output_dir / "media.mp4").write_bytes(b"media")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(
        download_service,
        "probe_exact_video_size",
        lambda url: 4,
        raising=False,
    )
    monkeypatch.setattr(
        download_service,
        "validate_source_url",
        lambda url, domains: validated.append((url, domains)),
    )
    source_url = "https://example.com/watch/item"
    direct_url = "https://example.com/media/item.mp4"
    record_with_fallback = SimpleNamespace(
        job_id="generic-best-job",
        inspection=SimpleNamespace(
            url=source_url,
            best_available=SimpleNamespace(url=direct_url, size_bytes=4),
        ),
    )
    runtime_settings = settings(tmp_path)

    result = download_service.download_media(
        record_with_fallback,
        best_option(),
        runtime_settings,
        threading.Event(),
    )

    assert result.path == tmp_path / "generic-best-job" / "media.mp4"
    assert captured["urls"] == [direct_url]
    assert validated == [
        (source_url, frozenset({"example.com"})),
        (direct_url, frozenset({"example.com"})),
    ]


def test_provider_alternate_page_is_revalidated_at_download_time(monkeypatch, tmp_path):
    source_url = "https://www.eporner.com/video-AbC123/example-title"
    alternate_url = "https://www.eporner.com/embed/AbC123"
    validated = []
    monkeypatch.setattr(
        download_service,
        "validate_source_url",
        lambda url, domains: validated.append((url, domains)),
    )
    record_with_alternate = SimpleNamespace(
        inspection=SimpleNamespace(url=source_url, download_url=alternate_url)
    )

    result = download_service._validated_transfer_url(
        record_with_alternate,
        option(),
        settings(tmp_path, allowed_domains=frozenset({"eporner.com"})),
    )

    assert result == alternate_url
    assert validated == [
        (source_url, frozenset({"eporner.com"})),
        (alternate_url, frozenset({"eporner.com"})),
    ]


def test_download_media_uses_candidate_policy_for_an_allowed_source_cdn(
    monkeypatch, tmp_path
):
    import yt_dlp

    captured = {}
    validated = []
    source_url = "https://example.com/watch/item"
    direct_url = "https://media.example.net/video/item.mp4"
    candidate_domains = frozenset({"media.example.net"})

    class FakeYoutubeDL:
        def __init__(self, options):
            captured.update(options)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def download(self, urls):
            captured["urls"] = urls
            output_dir = Path(captured["outtmpl"]).parent
            (output_dir / "media.mp4").write_bytes(b"media")

    def validate(url, domains):
        validated.append((url, domains))
        if url == direct_url and domains != candidate_domains:
            raise AssertionError("download did not reuse the inspected CDN policy")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(download_service, "probe_exact_video_size", lambda url: 4)
    monkeypatch.setattr(download_service, "validate_source_url", validate)
    record_with_fallback = SimpleNamespace(
        job_id="generic-cdn-best-job",
        inspection=SimpleNamespace(
            url=source_url,
            best_available=SimpleNamespace(
                url=direct_url,
                size_bytes=4,
                validation_domains=candidate_domains,
            ),
        ),
    )

    result = download_service.download_media(
        record_with_fallback,
        best_option(),
        settings(tmp_path),
        threading.Event(),
    )

    assert result.path == tmp_path / "generic-cdn-best-job" / "media.mp4"
    assert captured["urls"] == [direct_url]
    assert validated == [
        (source_url, frozenset({"example.com"})),
        (direct_url, candidate_domains),
    ]


def test_download_media_rejects_best_candidate_over_cap_before_network(
    monkeypatch, tmp_path
):
    import yt_dlp

    class UnexpectedYoutubeDL:
        def __init__(self, options):
            raise AssertionError("over-cap fallback must not reach yt-dlp")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", UnexpectedYoutubeDL)
    selected = best_option()
    monkeypatch.setattr(
        download_service,
        "probe_exact_video_size",
        lambda url: 11,
        raising=False,
    )
    record_with_stale_size = SimpleNamespace(
        job_id="pmv-over-cap",
        inspection=SimpleNamespace(
            url="https://pmvhaven.com/video/example_0123456789abcdef01234567",
            best_available=SimpleNamespace(
                url=(
                    "https://pmvhavencloud.s3.eu-west-par.io.cloud.ovh.net/"
                    "media/video.mp4"
                ),
                size_bytes=4,
                validation_domains=frozenset(
                    {"pmvhavencloud.s3.eu-west-par.io.cloud.ovh.net"}
                ),
            ),
        ),
    )

    with pytest.raises(download_service.DownloadError) as caught:
        download_service.download_media(
            record_with_stale_size,
            selected,
            settings(
                tmp_path,
                max_upload_bytes=10,
                allowed_domains=frozenset({"pmvhaven.com"}),
            ),
            threading.Event(),
        )

    assert caught.value.code == "output_limit"


def test_cleanup_rejects_a_path_outside_the_job_root(tmp_path):
    outside = tmp_path.parent / "outside-job-data"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError):
        download_service.cleanup_job_directory(tmp_path, "..")

    assert (outside / "keep.txt").exists()


def test_cleanup_unlinks_a_job_symlink_without_following_it(tmp_path):
    outside = tmp_path.parent / "outside-job-target"
    outside.mkdir()
    link = tmp_path / "job-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable in this Windows environment")

    download_service.cleanup_job_directory(tmp_path, "job-link")

    assert not link.exists()
    assert outside.exists()


def test_orphan_janitor_removes_only_stale_job_directories(tmp_path):
    old_job = tmp_path / "old-job"
    recent_job = tmp_path / "recent-job"
    marker = tmp_path / "keep.txt"
    old_job.mkdir()
    recent_job.mkdir()
    marker.write_text("keep", encoding="utf-8")
    os.utime(old_job, (1_000, 1_000))
    os.utime(recent_job, (1_075, 1_075))

    removed = download_service.cleanup_orphaned_job_directories(
        tmp_path,
        max_age_seconds=50,
        time_fn=lambda: 1_100,
    )

    assert removed == 1
    assert not old_job.exists()
    assert recent_job.exists()
    assert marker.read_text(encoding="utf-8") == "keep"


def test_orphan_janitor_preserves_unconfirmed_upload_until_safety_expiry(
    tmp_path,
):
    retained_job = tmp_path / "retained-job"
    retained_job.mkdir()
    upload_marker = retained_job / download_service.UNCONFIRMED_UPLOAD_MARKER
    upload_marker.touch()
    os.utime(upload_marker, (1_000, 1_000))
    os.utime(retained_job, (1_000, 1_000))

    removed = download_service.cleanup_orphaned_job_directories(
        tmp_path,
        max_age_seconds=50,
        unconfirmed_max_age_seconds=200,
        time_fn=lambda: 1_100,
    )

    assert removed == 0
    assert retained_job.exists()

    removed = download_service.cleanup_orphaned_job_directories(
        tmp_path,
        max_age_seconds=50,
        unconfirmed_max_age_seconds=200,
        time_fn=lambda: 1_201,
    )

    assert removed == 1
    assert not retained_job.exists()

