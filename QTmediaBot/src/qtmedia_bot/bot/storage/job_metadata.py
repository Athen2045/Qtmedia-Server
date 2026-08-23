"""Short-lived, URL-free operational metadata for completed bot jobs."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..services.jobs import JobRecord


TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


class JobMetadataStore:
    """Persist only short-lived terminal job facts needed for local recovery."""

    def __init__(
        self,
        database_path: Path,
        retention_seconds: int,
        time_fn: Callable[[], float] = time.time,
    ):
        self._database_path = database_path
        self._retention_seconds = retention_seconds
        self._time_fn = time_fn

    @property
    def database_path(self) -> Path:
        """Return the configured SQLite path without opening the database."""

        return self._database_path

    def _connect(self) -> sqlite3.Connection:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self._database_path)

    def initialize(self) -> None:
        """Create the minimal metadata schema and expiry indexes."""

        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_job_metadata (
                    job_id TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    status TEXT NOT NULL
                        CHECK(status IN ('completed', 'failed', 'cancelled')),
                    temp_dir TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    output_size INTEGER,
                    error_code TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_telegram_job_metadata_status_expiry
                ON telegram_job_metadata(status, expires_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_telegram_job_metadata_user_status
                ON telegram_job_metadata(user_id, status)
                """
            )

    def record_terminal(
        self,
        record: JobRecord,
        *,
        status: str,
        temp_dir: Path,
        output_size: int | None,
        error_code: str | None,
    ) -> None:
        """Upsert a terminal operational record without source metadata."""

        if status not in TERMINAL_STATUSES:
            raise ValueError("status must be a terminal job state")
        now = self._time_fn()
        expires_at = now + self._retention_seconds
        self.initialize()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO telegram_job_metadata (
                    job_id, chat_id, user_id, status, temp_dir, created_at,
                    updated_at, expires_at, output_size, error_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    chat_id = excluded.chat_id,
                    user_id = excluded.user_id,
                    status = excluded.status,
                    temp_dir = excluded.temp_dir,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at,
                    output_size = excluded.output_size,
                    error_code = excluded.error_code
                """,
                (
                    record.job_id,
                    record.chat_id,
                    record.user_id,
                    status,
                    str(temp_dir.resolve()),
                    now,
                    now,
                    expires_at,
                    output_size,
                    error_code,
                ),
            )

    def purge_expired(self) -> int:
        """Delete expired records and return their count."""

        self.initialize()
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM telegram_job_metadata WHERE expires_at <= ?",
                (self._time_fn(),),
            )
        return cursor.rowcount
