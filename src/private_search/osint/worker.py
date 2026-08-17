"""Validated subprocess launcher for one-shot JSON workers."""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from ..progress import ProgressEvent, parse_progress_line

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
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout_seconds,
        "shell": False,
        "input": request_text,
    }
    if env is not None:
        run_kwargs["env"] = dict(env)

    try:
        completed = subprocess.run(command, check=False, **run_kwargs)
    except subprocess.TimeoutExpired as error:
        raise WorkerExecutionError(
            f"worker timed out after {timeout_seconds} seconds",
        ) from error
    except OSError as error:
        raise WorkerExecutionError(
            "could not start worker",
            diagnostics=_truncate(str(error)),
        ) from error

    if completed.returncode != 0:
        diagnostics = completed.stderr or completed.stdout or "no diagnostic output"
        raise WorkerExecutionError(
            f"worker exited with code {completed.returncode}",
            diagnostics=_truncate(diagnostics),
        )

    response_text = completed.stdout or ""
    return _parse_single_json(response_text, stderr=completed.stderr or "")


def run_streaming_json_worker(
    command: Sequence[str],
    request: Mapping[str, object],
    *,
    cwd: Path,
    timeout_seconds: int,
    env: Mapping[str, str] | None = None,
    on_progress: Callable[[ProgressEvent], None] | None = None,
) -> object:
    """Run a JSON worker while forwarding structured stderr progress events.

    Workers keep their machine-readable response on stdout. Lines beginning
    with ``THEIA_PROGRESS `` are consumed as progress events; all other stderr
    output remains diagnostic text for failures. Two reader threads drain the
    pipes concurrently so a verbose worker cannot deadlock the parent.
    """

    request_text = json.dumps(request, separators=(",", ":"), ensure_ascii=False)
    process_kwargs: dict[str, object] = {
        "cwd": cwd,
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "shell": False,
    }
    if env is not None:
        process_kwargs["env"] = dict(env)

    try:
        process = subprocess.Popen(command, **process_kwargs)
    except OSError as error:
        raise WorkerExecutionError(
            "could not start worker",
            diagnostics=_truncate(str(error)),
        ) from error

    stdout_lines: list[str] = []
    diagnostics: list[str] = []

    def read_stdout() -> None:
        stream = process.stdout
        if stream is None:
            return
        stdout_lines.extend(stream)

    def read_stderr() -> None:
        stream = process.stderr
        if stream is None:
            return
        for line in stream:
            event = parse_progress_line(line.rstrip("\r\n"))
            if event is not None:
                if on_progress is not None:
                    try:
                        on_progress(event)
                    except Exception as callback_error:  # noqa: BLE001 - UI callbacks are best effort.
                        diagnostics.append(f"progress callback failed: {callback_error}\n")
                continue
            diagnostics.append(line)

    stdout_thread = threading.Thread(target=read_stdout, name="theia-worker-stdout")
    stderr_thread = threading.Thread(target=read_stderr, name="theia-worker-stderr")
    stdout_thread.start()
    stderr_thread.start()

    try:
        if process.stdin is not None:
            process.stdin.write(request_text)
            process.stdin.close()
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        process.kill()
        process.wait()
        stdout_thread.join()
        stderr_thread.join()
        raise WorkerExecutionError(
            f"worker timed out after {timeout_seconds} seconds",
            diagnostics=_truncate("".join(diagnostics)),
        ) from error
    except OSError as error:
        process.kill()
        process.wait()
        stdout_thread.join()
        stderr_thread.join()
        raise WorkerExecutionError(
            "worker communication failed",
            diagnostics=_truncate(str(error)),
        ) from error

    stdout_thread.join()
    stderr_thread.join()
    diagnostic_text = "".join(diagnostics)
    if process.returncode != 0:
        raise WorkerExecutionError(
            f"worker exited with code {process.returncode}",
            diagnostics=_truncate(diagnostic_text or "".join(stdout_lines) or "no diagnostic output"),
        )
    return _parse_single_json("".join(stdout_lines), stderr=diagnostic_text)


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
