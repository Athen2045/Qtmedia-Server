import sqlite3
from pathlib import Path

from qtmedia_bot.bot.services.inspection import MediaInspection
from qtmedia_bot.bot.services.jobs import JobCatalog
from qtmedia_bot.bot.services.quality import QualityOption
from qtmedia_bot.bot.storage.job_metadata import JobMetadataStore


def _claimed_record():
    catalog = JobCatalog()
    option = QualityOption("v720", "720p", 720, 4, False, "720", "video")
    inspection = MediaInspection(
        url="https://example.com/private-source",
        title="Private title",
        duration_seconds=30,
        formats=(),
    )
    job_id = catalog.create(123, 456, inspection, (option,))
    return catalog.claim_for_user(job_id, 123, 456, option.key)


def test_terminal_metadata_contains_only_operational_fields(tmp_path):
    database_path = tmp_path / "metadata.sqlite3"
    store = JobMetadataStore(database_path, retention_seconds=60)
    record = _claimed_record()

    store.initialize()
    store.record_terminal(
        record,
        status="completed",
        temp_dir=tmp_path / "jobs" / record.job_id,
        output_size=4,
        error_code=None,
    )

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT job_id, chat_id, user_id, status, temp_dir, output_size, error_code
            FROM telegram_job_metadata
            WHERE job_id = ?
            """,
            (record.job_id,),
        ).fetchone()
        columns = {
            column[1]
            for column in connection.execute("PRAGMA table_info(telegram_job_metadata)")
        }

    assert row == (
        record.job_id,
        456,
        123,
        "completed",
        str((tmp_path / "jobs" / record.job_id).resolve()),
        4,
        None,
    )
    assert {"url", "title", "cookie", "filename"}.isdisjoint(columns)


def test_purge_expired_terminal_metadata(tmp_path):
    current_time = 1000.0
    database_path = tmp_path / "metadata.sqlite3"
    store = JobMetadataStore(
        database_path,
        retention_seconds=60,
        time_fn=lambda: current_time,
    )
    record = _claimed_record()

    store.initialize()
    store.record_terminal(
        record,
        status="failed",
        temp_dir=Path("var/telegram_jobs") / record.job_id,
        output_size=None,
        error_code="download_failed",
    )
    current_time += 61

    assert store.purge_expired() == 1
    with sqlite3.connect(database_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM telegram_job_metadata"
        ).fetchone()[0]
    assert count == 0

