"""Short-lived in-memory job catalog for inspection callbacks."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from .inspection import MediaInspection
from .quality import QualityOption

ACTIVE_STATUSES = frozenset({"queued", "downloading", "uploading"})
CANCELLABLE_STATUSES = frozenset({"awaiting_format", "queued", "downloading"})
INTERACTION_STATUSES = CANCELLABLE_STATUSES | {"uploading"}


@dataclass(frozen=True, slots=True)
# pylint: disable=too-many-instance-attributes
class JobRecord:
    """Sensitive inspection state held only while a user chooses a format."""

    job_id: str
    user_id: int
    chat_id: int
    inspection: MediaInspection
    options: tuple[QualityOption, ...]
    expires_at: float
    inspection_message_id: int | None = None
    status: str = "awaiting_format"


class JobCatalog:
    """Thread-safe, expiring memory store with no persistence layer."""

    def __init__(self, ttl_seconds: int = 600, time_fn: Callable[[], float] = time.time):
        """Create an in-memory catalog with a configurable clock for tests."""

        self._ttl_seconds = ttl_seconds
        self._time_fn = time_fn
        self._records: dict[str, JobRecord] = {}
        self._lock = threading.Lock()

    def create(
        self,
        user_id: int,
        chat_id: int,
        inspection: MediaInspection,
        options: tuple[QualityOption, ...],
        inspection_message_id: int | None = None,
    ) -> str:
        """Create and return an opaque record identifier."""

        with self._lock:
            self._remove_expired_locked(self._time_fn())
            return self._create_locked(
                user_id,
                chat_id,
                inspection,
                options,
                inspection_message_id,
            )

    def try_create(
        self,
        user_id: int,
        chat_id: int,
        inspection: MediaInspection,
        options: tuple[QualityOption, ...],
        inspection_message_id: int | None = None,
    ) -> str | None:
        """Atomically create a job only while the owner has no interaction."""

        with self._lock:
            self._remove_expired_locked(self._time_fn())
            if any(
                record.user_id == user_id
                and record.chat_id == chat_id
                and record.status in INTERACTION_STATUSES
                for record in self._records.values()
            ):
                return None
            return self._create_locked(
                user_id,
                chat_id,
                inspection,
                options,
                inspection_message_id,
            )

    def _create_locked(
        self,
        user_id: int,
        chat_id: int,
        inspection: MediaInspection,
        options: tuple[QualityOption, ...],
        inspection_message_id: int | None,
    ) -> str:
        job_id = secrets.token_urlsafe(9)
        self._records[job_id] = JobRecord(
            job_id=job_id,
            user_id=user_id,
            chat_id=chat_id,
            inspection=inspection,
            options=options,
            expires_at=self._time_fn() + self._ttl_seconds,
            inspection_message_id=inspection_message_id,
        )
        return job_id

    def get_for_user(
        self, job_id: str, user_id: int, chat_id: int
    ) -> JobRecord | None:
        """Return an unexpired record only for its owning user and chat."""

        with self._lock:
            record = self._records.get(job_id)
            if record is None or record.expires_at <= self._time_fn():
                self._records.pop(job_id, None)
                return None
            if record.user_id != user_id or record.chat_id != chat_id:
                return None
            return record

    def claim_for_user(
        self, job_id: str, user_id: int, chat_id: int, option_key: str
    ) -> JobRecord | None:
        """Atomically claim one available option for its owning chat."""

        with self._lock:
            record = self._records.get(job_id)
            if record is None or record.expires_at <= self._time_fn():
                self._records.pop(job_id, None)
                return None
            if (
                record.user_id != user_id
                or record.chat_id != chat_id
                or record.status != "awaiting_format"
            ):
                return None
            if not any(item.key == option_key for item in record.options):
                return None
            claimed = replace(record, status="queued")
            self._records[job_id] = claimed
            return claimed

    def active_for_user(self, user_id: int, chat_id: int) -> JobRecord | None:
        """Return the user's current queued or running job, if any."""

        with self._lock:
            self._remove_expired_locked(self._time_fn())
            return next(
                (
                    record
                    for record in self._records.values()
                    if record.user_id == user_id
                    and record.chat_id == chat_id
                    and record.status in ACTIVE_STATUSES
                ),
                None,
            )

    def current_for_user(self, user_id: int, chat_id: int) -> JobRecord | None:
        """Return any unexpired interaction owned by the user and chat."""

        with self._lock:
            self._remove_expired_locked(self._time_fn())
            return next(
                (
                    record
                    for record in self._records.values()
                    if record.user_id == user_id
                    and record.chat_id == chat_id
                    and record.status in INTERACTION_STATUSES
                ),
                None,
            )

    def set_status(self, job_id: str, status: str) -> bool:
        """Update a claimed job state while it remains in the catalog."""

        with self._lock:
            record = self._records.get(job_id)
            if record is None or record.expires_at <= self._time_fn():
                self._records.pop(job_id, None)
                return False
            self._records[job_id] = replace(record, status=status)
            return True

    def cancel_for_user(self, job_id: str, user_id: int, chat_id: int) -> bool:
        """Mark a queued or running job cancelled for its owner only."""

        with self._lock:
            record = self._records.get(job_id)
            if record is None or record.expires_at <= self._time_fn():
                self._records.pop(job_id, None)
                return False
            if (
                record.user_id != user_id
                or record.chat_id != chat_id
                or record.status not in CANCELLABLE_STATUSES
            ):
                return False
            self._records[job_id] = replace(record, status="cancelled")
            return True

    def remove(self, job_id: str) -> None:
        """Remove a terminal job record from memory."""

        with self._lock:
            self._records.pop(job_id, None)

    def remove_expired(self, now: float | None = None) -> int:
        """Remove expired records and return the number removed."""

        current_time = self._time_fn() if now is None else now
        with self._lock:
            return self._remove_expired_locked(current_time)

    def _remove_expired_locked(self, current_time: float) -> int:
        expired = [
            job_id
            for job_id, record in self._records.items()
            if record.expires_at <= current_time
        ]
        for job_id in expired:
            self._records.pop(job_id, None)
        return len(expired)
