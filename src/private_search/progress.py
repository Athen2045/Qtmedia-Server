"""Machine-readable progress events shared by Theia and isolated workers."""

from __future__ import annotations

import json
from dataclasses import dataclass

PROGRESS_PREFIX = "THEIA_PROGRESS "


@dataclass(frozen=True)
class ProgressEvent:
    """One best-effort operation progress update."""

    phase: str
    message: str
    completed: int | None = None
    total: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.phase, str) or not self.phase.strip():
            raise ValueError("progress phase must be a non-empty string")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("progress message must be a non-empty string")
        if self.completed is not None and (
            isinstance(self.completed, bool)
            or not isinstance(self.completed, int)
            or self.completed < 0
        ):
            raise ValueError("progress completed must be a non-negative integer")
        if self.total is not None and (
            isinstance(self.total, bool)
            or not isinstance(self.total, int)
            or self.total < 1
        ):
            raise ValueError("progress total must be a positive integer")
        if (
            self.completed is not None
            and self.total is not None
            and self.completed > self.total
        ):
            raise ValueError("progress completed cannot exceed total")


def format_progress_event(event: ProgressEvent) -> str:
    """Serialize an event for a worker stderr line."""

    payload: dict[str, object] = {
        "phase": event.phase,
        "message": event.message,
    }
    if event.completed is not None:
        payload["completed"] = event.completed
    if event.total is not None:
        payload["total"] = event.total
    return PROGRESS_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def parse_progress_line(line: str) -> ProgressEvent | None:
    """Parse one progress line, returning ``None`` for diagnostics or invalid data."""

    if not isinstance(line, str) or not line.startswith(PROGRESS_PREFIX):
        return None
    try:
        payload = json.loads(line[len(PROGRESS_PREFIX) :].strip())
        if not isinstance(payload, dict):
            return None
        return ProgressEvent(
            phase=payload.get("phase"),
            message=payload.get("message"),
            completed=payload.get("completed"),
            total=payload.get("total"),
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


__all__ = ["PROGRESS_PREFIX", "ProgressEvent", "format_progress_event", "parse_progress_line"]
