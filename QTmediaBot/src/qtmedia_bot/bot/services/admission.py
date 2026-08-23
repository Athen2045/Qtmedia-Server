"""Privacy-minimal request and transfer-queue admission control."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable


class AdmissionController:
    """Apply a per-user sliding window and a bounded idempotent job queue."""

    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: float,
        max_queued_jobs: int,
        clock: Callable[[], float] = time.monotonic,
    ):
        if max_requests <= 0 or window_seconds <= 0 or max_queued_jobs <= 0:
            raise ValueError("admission limits must be positive")
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._max_queued_jobs = max_queued_jobs
        self._clock = clock
        self._requests: dict[int, deque[float]] = {}
        self._queued_jobs: set[str] = set()
        self._lock = threading.Lock()

    def allow_request(self, user_id: int) -> bool:
        """Consume one request slot when the user's window has capacity."""

        with self._lock:
            now = self._clock()
            cutoff = now - self._window_seconds
            timestamps = self._requests.setdefault(user_id, deque())
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= self._max_requests:
                return False
            timestamps.append(now)
            return True

    def try_enter_queue(self, job_id: str) -> bool:
        """Idempotently reserve one bounded waiting-job slot."""

        with self._lock:
            if job_id in self._queued_jobs:
                return True
            if len(self._queued_jobs) >= self._max_queued_jobs:
                return False
            self._queued_jobs.add(job_id)
            return True

    def leave_queue(self, job_id: str) -> None:
        """Release a waiting-job slot if it is currently reserved."""

        with self._lock:
            self._queued_jobs.discard(job_id)
