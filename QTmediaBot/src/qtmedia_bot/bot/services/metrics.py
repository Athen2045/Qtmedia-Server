"""Privacy-safe phase timing for Telegram transfer jobs."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ALLOWED_PHASES = frozenset({"queue", "download", "upload", "cleanup"})
SAFE_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SAFE_OUTCOME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True, slots=True)
class PhaseMetric:
    """One numeric-only phase measurement for an opaque job identifier."""

    job_id: str
    phase: str
    duration_ms: int
    outcome: str
    byte_count: int | None


def _log_metric(metric: PhaseMetric) -> None:
    logger.info(
        "Job phase metric: job_id=%s phase=%s duration_ms=%d outcome=%s bytes=%s",
        metric.job_id,
        metric.phase,
        metric.duration_ms,
        metric.outcome,
        metric.byte_count if metric.byte_count is not None else "unknown",
    )


class JobPhaseRecorder:
    """Measure one active transfer phase without accepting private metadata."""

    def __init__(
        self,
        job_id: str,
        *,
        clock: Callable[[], float] = time.perf_counter,
        sink: Callable[[PhaseMetric], None] | None = None,
    ):
        if not SAFE_JOB_ID.fullmatch(job_id):
            raise ValueError("job_id must be an opaque identifier")
        self._job_id = job_id
        self._clock = clock
        self._sink = _log_metric if sink is None else sink
        self._active_phase: str | None = None
        self._started_at: float | None = None

    def start(self, phase: str) -> None:
        """Begin one allowlisted phase."""

        if phase not in ALLOWED_PHASES:
            raise ValueError("phase is not supported")
        if self._active_phase is not None:
            raise ValueError("a phase is already active")
        self._active_phase = phase
        self._started_at = self._clock()

    def finish(
        self,
        *,
        outcome: str = "completed",
        byte_count: int | None = None,
    ) -> None:
        """Finish the active phase and emit one bounded measurement."""

        if self._active_phase is None or self._started_at is None:
            raise ValueError("no phase is active")
        if not SAFE_OUTCOME.fullmatch(outcome):
            raise ValueError("outcome must be a stable code")
        if (
            byte_count is not None
            and (isinstance(byte_count, bool) or not isinstance(byte_count, int))
        ) or (byte_count is not None and byte_count < 0):
            raise ValueError("byte_count must be a non-negative integer")

        duration_ms = max(0, round((self._clock() - self._started_at) * 1_000))
        metric = PhaseMetric(
            job_id=self._job_id,
            phase=self._active_phase,
            duration_ms=duration_ms,
            outcome=outcome,
            byte_count=byte_count,
        )
        self._active_phase = None
        self._started_at = None
        self._sink(metric)

    def fail_active(self, error_code: str) -> None:
        """Close the active phase once with a stable failure code."""

        if self._active_phase is not None:
            self.finish(outcome=error_code)
