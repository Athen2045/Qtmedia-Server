import asyncio
from unittest.mock import AsyncMock

from qtmedia_bot.bot.services.progress import (
    PREPARING_TEXT,
    UPLOAD_PENDING_TEXT,
    DownloadProgress,
    TelegramProgressReporter,
    render_download_progress,
)


def test_render_download_progress_uses_real_byte_total_and_speed():
    text = render_download_progress(
        "720p",
        DownloadProgress(
            downloaded_bytes=64_000_000,
            total_bytes=100_000_000,
            estimated_total_bytes=None,
            speed_bytes_per_second=5_000_000,
        ),
    )

    assert "Downloading 720p" in text
    assert "64%" in text
    assert "64.0 MB / 100.0 MB" in text
    assert "5.0 MB/s" in text


def test_render_download_progress_marks_an_estimated_total_and_never_invents_speed():
    text = render_download_progress(
        "MP3",
        DownloadProgress(
            downloaded_bytes=8_000_000,
            total_bytes=None,
            estimated_total_bytes=10_000_000,
            speed_bytes_per_second=None,
        ),
    )

    assert "~10.0 MB" in text
    assert "speed unavailable" in text
    assert "80%" in text


def test_reporter_coalesces_worker_updates_and_immediately_shows_phase_changes():
    async def exercise():
        edit_text = AsyncMock()
        reporter = TelegramProgressReporter(
            edit_text, label="720p", update_interval_seconds=60
        )
        await reporter.start()
        reporter.publish_from_worker(
            DownloadProgress(1_000_000, 10_000_000, None, 1_000_000)
        )
        reporter.publish_from_worker(
            DownloadProgress(2_000_000, 10_000_000, None, 2_000_000)
        )
        await asyncio.sleep(0.05)
        reporter.show_preparing_from_worker()
        await asyncio.sleep(0.05)
        await reporter.show_uploading()

        return [call.args[0] for call in edit_text.await_args_list]

    edits = asyncio.run(exercise())

    assert sum("2.0 MB / 10.0 MB" in text for text in edits) == 1
    assert PREPARING_TEXT in edits
    assert edits[-1] == UPLOAD_PENDING_TEXT

