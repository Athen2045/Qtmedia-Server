"""Bounded in-memory media and download job catalog."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable

from qtmedia.desktop_service.models import InspectedMedia


class SessionError(LookupError):
    pass


class SessionCatalog:
    def __init__(
        self,
        *,
        max_media: int = 64,
        max_jobs: int = 4,
        ttl_seconds: float = 30 * 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_media = max_media
        self._max_jobs = max_jobs
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._media: OrderedDict[str, tuple[float, InspectedMedia]] = OrderedDict()
        self._jobs: dict[str, threading.Event] = {}
        self._lock = threading.RLock()

    def _prune(self) -> None:
        cutoff = self._clock() - self._ttl_seconds
        expired = [key for key, (created, _media) in self._media.items() if created < cutoff]
        for key in expired:
            self._media.pop(key, None)

    def store_media(self, media: InspectedMedia) -> None:
        with self._lock:
            self._prune()
            self._media[media.media_id] = (self._clock(), media)
            self._media.move_to_end(media.media_id)
            while len(self._media) > self._max_media:
                self._media.popitem(last=False)

    def get_media(self, media_id: str) -> InspectedMedia:
        with self._lock:
            value = self._media.get(media_id)
            if value is None:
                raise SessionError("unknown_media")
            created, media = value
            if created < self._clock() - self._ttl_seconds:
                self._media.pop(media_id, None)
                raise SessionError("expired_media")
            return media

    def register_job(self, job_id: str, cancel: threading.Event) -> None:
        with self._lock:
            if len(self._jobs) >= self._max_jobs:
                raise SessionError("too_many_jobs")
            self._jobs[job_id] = cancel

    def cancel_job(self, job_id: str) -> None:
        with self._lock:
            cancel = self._jobs.get(job_id)
            if cancel is None:
                raise SessionError("unknown_job")
            cancel.set()

    def remove_job(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)

    def cancel_all(self) -> None:
        with self._lock:
            for cancel in self._jobs.values():
                cancel.set()
