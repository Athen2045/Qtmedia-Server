import asyncio
import sqlite3
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from telegram.error import NetworkError, TelegramError, TimedOut

from qtmedia_bot.bot.config import BotSettings
from qtmedia_bot.bot.services import downloads as download_service
from qtmedia_bot.bot.services.downloads import DownloadedMedia, DownloadManager
from qtmedia_bot.bot.services.inspection import MediaInspection
from qtmedia_bot.bot.services.jobs import JobCatalog
from qtmedia_bot.bot.services.progress import DownloadProgress
from qtmedia_bot.bot.services.quality import QualityOption
from qtmedia_bot.bot.storage import JobMetadataStore


def option():
    return QualityOption("v720", "720p", 720, 4, False, "720", "video")


def settings(
    job_root: Path,
    *,
    local_mode=False,
    download_timeout_seconds=60,
    upload_timeout_seconds=60,
    unconfirmed_upload_retention_seconds=60,
):
    return BotSettings(
        token="test-token",
        base_url="https://api.example/bot",
        file_base_url="https://api.example/file/bot",
        local_mode=local_mode,
        private_chats_only=True,
        allowed_user_ids=frozenset({123}),
        allowed_domains=frozenset({"example.com"}),
        job_root=job_root,
        disk_reserve_bytes=1,
        max_upload_bytes=10,
        download_timeout_seconds=download_timeout_seconds,
        upload_timeout_seconds=upload_timeout_seconds,
        unconfirmed_upload_retention_seconds=(
            unconfirmed_upload_retention_seconds
        ),
    )


def claimed_job(tmp_path):
    catalog = JobCatalog()
    inspection = MediaInspection(
        url="https://example.com/private-source",
        title="Private title",
        duration_seconds=30,
        formats=(),
    )
    selected = option()
    job_id = catalog.create(123, 456, inspection, (selected,))
    return catalog, catalog.claim_for_user(job_id, 123, 456, selected.key), selected


class FakeMessage:
    def __init__(self):
        self.reply_video = AsyncMock()
        self.reply_audio = AsyncMock()
        self.reply_document = AsyncMock()


class RecordingProgressReporter:
    def __init__(self):
        self.events = []

    async def start(self):
        self.events.append("start")

    def publish_from_worker(self, progress):
        self.events.append(("download", progress))

    def show_preparing_from_worker(self):
        self.events.append("preparing_from_worker")

    async def show_preparing(self):
        self.events.append("preparing")

    async def show_uploading(self):
        self.events.append("uploading")

    async def stop(self):
        self.events.append("stop")


class RecordingDeliveryTransport:
    def __init__(self):
        self.deliveries = []

    async def deliver(self, message, media):
        self.deliveries.append((message, media))


class RecordingAdmission:
    def __init__(self):
        self.left = []

    def leave_queue(self, job_id):
        self.left.append(job_id)


def test_download_hook_forwards_only_numeric_download_progress():
    received = []
    hook = download_service._progress_hook(threading.Event(), received.append)

    hook(
        {
            "status": "downloading",
            "downloaded_bytes": 1_000_000,
            "total_bytes": 2_000_000,
            "total_bytes_estimate": 3_000_000,
            "speed": 500_000,
            "filename": "never-forward-this.mp4",
        }
    )

    assert received == [DownloadProgress(1_000_000, 2_000_000, 3_000_000, 500_000)]


def test_manager_reports_preparation_then_honest_upload_before_media_reply(
    monkeypatch, tmp_path
):
    catalog, record, selected = claimed_job(tmp_path)
    message = FakeMessage()
    reporter = RecordingProgressReporter()

    def fake_download(
        job,
        option_value,
        runtime_settings,
        cancel_event,
        *,
        progress_callback,
        preparing_callback,
    ):
        progress_callback(DownloadProgress(1, 2, None, 1))
        preparing_callback()
        job_dir = runtime_settings.job_root / job.job_id
        job_dir.mkdir(parents=True)
        output = job_dir / "media.mp4"
        output.write_bytes(b"media")
        return DownloadedMedia(output, option_value.media_type)

    async def upload_after_status(**kwargs):
        assert reporter.events[-1] == "uploading"

    message.reply_video.side_effect = upload_after_status
    monkeypatch.setattr(download_service, "download_media", fake_download)
    manager = DownloadManager(catalog, settings(tmp_path))

    asyncio.run(manager.run(record, selected, message, reporter))

    assert reporter.events[:2] == ["start", ("download", DownloadProgress(1, 2, None, 1))]
    assert "preparing_from_worker" in reporter.events
    assert reporter.events.index("preparing") < reporter.events.index("uploading")
    assert reporter.events[-1] == "stop"


def test_manager_uploads_by_path_and_cleans_after_success(monkeypatch, tmp_path):
    catalog, record, selected = claimed_job(tmp_path)
    message = FakeMessage()

    def fake_download(job, option_value, runtime_settings, cancel_event):
        job_dir = runtime_settings.job_root / job.job_id
        job_dir.mkdir(parents=True)
        output = job_dir / "media.mp4"
        output.write_bytes(b"media")
        return DownloadedMedia(output, option_value.media_type)

    monkeypatch.setattr(download_service, "download_media", fake_download)
    manager = DownloadManager(catalog, settings(tmp_path))

    asyncio.run(manager.run(record, selected, message))

    message.reply_video.assert_awaited_once()
    input_file = message.reply_video.await_args.kwargs["video"]
    assert input_file.filename == "media.mp4"
    assert input_file.input_file_content.name.endswith("media.mp4")
    assert not (tmp_path / record.job_id).exists()
    assert catalog.get_for_user(record.job_id, 123, 456) is None


def test_manager_delegates_delivery_through_transport_seam(monkeypatch, tmp_path):
    catalog, record, selected = claimed_job(tmp_path)
    message = FakeMessage()
    delivery = RecordingDeliveryTransport()

    def fake_download(job, option_value, runtime_settings, cancel_event):
        job_dir = runtime_settings.job_root / job.job_id
        job_dir.mkdir(parents=True)
        output = job_dir / "media.mp4"
        output.write_bytes(b"media")
        return DownloadedMedia(output, option_value.media_type)

    monkeypatch.setattr(download_service, "download_media", fake_download)
    manager = DownloadManager(
        catalog,
        settings(tmp_path),
        delivery=delivery,
    )

    asyncio.run(manager.run(record, selected, message))

    assert len(delivery.deliveries) == 1
    delivered_message, delivered_media = delivery.deliveries[0]
    assert delivered_message is message
    assert delivered_media.media_type == "video"
    assert delivered_media.path.name == "media.mp4"


def test_manager_releases_admission_queue_on_semaphore_entry(monkeypatch, tmp_path):
    catalog, record, selected = claimed_job(tmp_path)
    message = FakeMessage()
    admission = RecordingAdmission()

    def fake_download(job, option_value, runtime_settings, cancel_event):
        job_dir = runtime_settings.job_root / job.job_id
        job_dir.mkdir(parents=True)
        output = job_dir / "media.mp4"
        output.write_bytes(b"media")
        return DownloadedMedia(output, option_value.media_type)

    monkeypatch.setattr(download_service, "download_media", fake_download)
    manager = DownloadManager(
        catalog,
        settings(tmp_path),
        admission=admission,
    )

    asyncio.run(manager.run(record, selected, message))

    assert admission.left[0] == record.job_id


def test_manager_records_completed_metadata_after_cleanup(monkeypatch, tmp_path):
    catalog, record, selected = claimed_job(tmp_path)
    message = FakeMessage()
    metadata_path = tmp_path / "metadata.sqlite3"
    metadata = JobMetadataStore(metadata_path, retention_seconds=60)

    def fake_download(job, option_value, runtime_settings, cancel_event):
        job_dir = runtime_settings.job_root / job.job_id
        job_dir.mkdir(parents=True)
        output = job_dir / "media.mp4"
        output.write_bytes(b"media")
        return DownloadedMedia(output, option_value.media_type)

    monkeypatch.setattr(download_service, "download_media", fake_download)
    manager = DownloadManager(catalog, settings(tmp_path), metadata)

    asyncio.run(manager.run(record, selected, message))

    with sqlite3.connect(metadata_path) as connection:
        row = connection.execute(
            """
            SELECT status, output_size, error_code
            FROM telegram_job_metadata
            WHERE job_id = ?
            """,
            (record.job_id,),
        ).fetchone()
    assert row == ("completed", 5, None)
    assert not (tmp_path / record.job_id).exists()


def test_manager_uses_local_file_uri_in_local_mode(monkeypatch, tmp_path):
    catalog, record, selected = claimed_job(tmp_path)
    message = FakeMessage()

    def fake_download(job, option_value, runtime_settings, cancel_event):
        job_dir = runtime_settings.job_root / job.job_id
        job_dir.mkdir(parents=True)
        output = job_dir / "media.mp4"
        output.write_bytes(b"media")
        return DownloadedMedia(output, option_value.media_type)

    monkeypatch.setattr(download_service, "download_media", fake_download)
    manager = DownloadManager(catalog, settings(tmp_path, local_mode=True))

    asyncio.run(manager.run(record, selected, message))

    assert message.reply_video.await_args.kwargs["video"] == (
        tmp_path / record.job_id / "media.mp4"
    )


def test_manager_cleans_when_telegram_upload_fails(monkeypatch, tmp_path):
    catalog, record, selected = claimed_job(tmp_path)
    message = FakeMessage()
    message.reply_video.side_effect = TelegramError("upload failed")

    def fake_download(job, option_value, runtime_settings, cancel_event):
        job_dir = runtime_settings.job_root / job.job_id
        job_dir.mkdir(parents=True)
        output = job_dir / "media.mp4"
        output.write_bytes(b"media")
        return DownloadedMedia(output, option_value.media_type)

    monkeypatch.setattr(download_service, "download_media", fake_download)
    manager = DownloadManager(catalog, settings(tmp_path))

    with pytest.raises(download_service.DownloadError, match="upload_failed"):
        asyncio.run(manager.run(record, selected, message))

    assert not (tmp_path / record.job_id).exists()


def test_manager_marks_upload_timeout_as_unconfirmed_not_failed(
    monkeypatch, tmp_path
):
    catalog, record, selected = claimed_job(tmp_path)
    message = FakeMessage()
    message.reply_video.side_effect = TimedOut()

    def fake_download(job, option_value, runtime_settings, cancel_event):
        job_dir = runtime_settings.job_root / job.job_id
        job_dir.mkdir(parents=True)
        output = job_dir / "media.mp4"
        output.write_bytes(b"media")
        return DownloadedMedia(output, option_value.media_type)

    monkeypatch.setattr(download_service, "download_media", fake_download)
    manager = DownloadManager(catalog, settings(tmp_path, local_mode=True))

    with pytest.raises(download_service.DownloadError, match="upload_unconfirmed"):
        asyncio.run(manager.run(record, selected, message))

    assert (tmp_path / record.job_id / "media.mp4").read_bytes() == b"media"


def test_manager_deletes_retained_unconfirmed_upload_after_expiry(
    monkeypatch, tmp_path
):
    catalog, record, selected = claimed_job(tmp_path)
    message = FakeMessage()
    message.reply_video.side_effect = TimedOut()

    def fake_download(job, option_value, runtime_settings, cancel_event):
        job_dir = runtime_settings.job_root / job.job_id
        job_dir.mkdir(parents=True)
        output = job_dir / "media.mp4"
        output.write_bytes(b"media")
        return DownloadedMedia(output, option_value.media_type)

    monkeypatch.setattr(download_service, "download_media", fake_download)
    manager = DownloadManager(
        catalog,
        settings(
            tmp_path,
            local_mode=True,
            unconfirmed_upload_retention_seconds=0.01,
        ),
    )

    async def exercise():
        with pytest.raises(download_service.DownloadError, match="upload_unconfirmed"):
            await manager.run(record, selected, message)
        assert (tmp_path / record.job_id / "media.mp4").exists()
        await asyncio.sleep(0.05)

    asyncio.run(exercise())

    assert not (tmp_path / record.job_id).exists()


def test_manager_marks_network_upload_error_as_unconfirmed(
    monkeypatch, tmp_path
):
    catalog, record, selected = claimed_job(tmp_path)
    message = FakeMessage()
    message.reply_video.side_effect = NetworkError("connection lost")

    def fake_download(job, option_value, runtime_settings, cancel_event):
        job_dir = runtime_settings.job_root / job.job_id
        job_dir.mkdir(parents=True)
        output = job_dir / "media.mp4"
        output.write_bytes(b"media")
        return DownloadedMedia(output, option_value.media_type)

    monkeypatch.setattr(download_service, "download_media", fake_download)
    manager = DownloadManager(catalog, settings(tmp_path))

    with pytest.raises(download_service.DownloadError, match="upload_unconfirmed"):
        asyncio.run(manager.run(record, selected, message))


def test_manager_uses_dedicated_upload_deadline(monkeypatch, tmp_path):
    catalog, record, selected = claimed_job(tmp_path)
    message = FakeMessage()

    def fake_download(job, option_value, runtime_settings, cancel_event):
        job_dir = runtime_settings.job_root / job.job_id
        job_dir.mkdir(parents=True)
        output = job_dir / "media.mp4"
        output.write_bytes(b"media")
        return DownloadedMedia(output, option_value.media_type)

    async def wait_forever(**kwargs):
        del kwargs
        await asyncio.Event().wait()

    message.reply_video.side_effect = wait_forever
    monkeypatch.setattr(download_service, "download_media", fake_download)
    manager = DownloadManager(
        catalog,
        settings(
            tmp_path,
            download_timeout_seconds=1,
            upload_timeout_seconds=0.01,
        ),
    )

    started = time.perf_counter()
    with pytest.raises(download_service.DownloadError, match="upload_unconfirmed"):
        asyncio.run(manager.run(record, selected, message))
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5


def test_manager_cancellation_sets_worker_event_and_cleans(monkeypatch, tmp_path):
    catalog, record, selected = claimed_job(tmp_path)
    message = FakeMessage()
    started = threading.Event()

    def fake_download(job, option_value, runtime_settings, cancel_event):
        started.set()
        cancel_event.wait(timeout=2)
        raise download_service.DownloadCancelled()

    monkeypatch.setattr(download_service, "download_media", fake_download)
    manager = DownloadManager(catalog, settings(tmp_path))

    async def exercise():
        task = asyncio.create_task(manager.run(record, selected, message))
        assert await asyncio.to_thread(started.wait, 1)
        assert manager.cancel_for_user(123, 456) is True
        with pytest.raises(download_service.DownloadCancelled):
            await task

    asyncio.run(exercise())

    assert not (tmp_path / record.job_id).exists()

