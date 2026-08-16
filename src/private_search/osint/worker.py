"""Validated subprocess launcher for one-shot JSON workers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from collections.abc import Mapping, Sequence

_DIAGNOSTIC_LIMIT = 2000


class WorkerExecutionError(RuntimeError):
    """Raised when a worker cannot start, respond, or return valid JSON."""

    def __init__(self, message: str, diagnostics: str = "") -> None:
        self.user_message = message
        self.diagnostics = _truncate(diagnostics)
        super().__init__(self._format())

    def _format(self) -> str:
        if self.diagnostics:
            return f"{self.user_message}: {self.diagnostics}"
        return self.user_message

    def __str__(self) -> str:  # pragma: no cover - delegated to _format
        return self._format()


def run_json_worker(
    command: Sequence[str],
    request: Mapping[str, object],
    *,
    cwd: Path,
    timeout_seconds: int,
    env: Mapping[str, str] | None = None,
) -> object:
    """Run a worker process and return its single JSON response value."""

    request_text = json.dumps(request, separators=(",", ":"), ensure_ascii=False)
    run_kwargs: dict[str, object] = {
        "cwd": cwd,
        "capture_output": True,
        "text": True,
        "timeout": timeout_seconds,
        "shell": False,
        "input": request_text,
    }
    if env is not None:
        run_kwargs["env"] = dict(env)

    try:
        completed = subprocess.run(command, **run_kwargs)
    except subprocess.TimeoutExpired as error:
        raise WorkerExecutionError(
            f"worker timed out after {timeout_seconds} seconds",
        ) from error
    except OSError as error:
        raise WorkerExecutionError(f"could not start worker: {error}") from error

    if completed.returncode != 0:
        diagnostics = completed.stderr or completed.stdout or "no diagnostic output"
        raise WorkerExecutionError(
            f"worker exited with code {completed.returncode}",
            diagnostics=_truncate(diagnostics),
        )

    response_text = completed.stdout or ""
    return _parse_single_json(response_text, stderr=completed.stderr or "")


def _parse_single_json(text: str, *, stderr: str) -> object:
    stripped = text.strip()
    if not stripped:
        raise WorkerExecutionError(
            "worker produced invalid JSON",
            diagnostics=_truncate(stderr or text or "no response body"),
        )

    decoder = json.JSONDecoder()
    try:
        value, index = decoder.raw_decode(stripped)
    except json.JSONDecodeError as error:
        raise WorkerExecutionError(
            "worker produced invalid JSON",
            diagnostics=_truncate(stderr or text or str(error)),
        ) from error

    if stripped[index:].strip():
        raise WorkerExecutionError(
            "worker produced invalid JSON",
            diagnostics=_truncate(stderr or text or "extra output after JSON value"),
        )
    return value


def _truncate(text: object) -> str:
    if not isinstance(text, str):
        text = str(text)
    return text[:_DIAGNOSTIC_LIMIT]

