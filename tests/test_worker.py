from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from private_search.osint.worker import (
    WorkerExecutionError,
    run_json_worker,
    run_streaming_json_worker,
)


def test_run_json_worker_sends_json_request_and_parses_exactly_one_value(
    monkeypatch, tmp_path: Path
):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": '{"ok": true, "results": [1, 2, 3]}',
                "stderr": "",
            },
        )()

    monkeypatch.setattr("private_search.osint.worker.subprocess.run", fake_run)

    result = run_json_worker(
        ["worker.exe", "--json"],
        {"username": "alice", "limit": 3},
        cwd=tmp_path,
        timeout_seconds=17,
        env={"PRIVATE_SEARCH_TEST": "1"},
    )

    assert result == {"ok": True, "results": [1, 2, 3]}
    command, kwargs = calls[0]
    assert command == ["worker.exe", "--json"]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 17
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["check"] is False
    assert kwargs["input"] is not None
    assert json.loads(kwargs["input"]) == {"username": "alice", "limit": 3}
    assert kwargs["env"] == {"PRIVATE_SEARCH_TEST": "1"}


def test_run_json_worker_rejects_trailing_non_whitespace_after_json(
    monkeypatch, tmp_path: Path
):
    def fake_run(command, **kwargs):
        return type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": '{"ok": true} trailing',
                "stderr": "",
            },
        )()

    monkeypatch.setattr("private_search.osint.worker.subprocess.run", fake_run)

    with pytest.raises(WorkerExecutionError, match="JSON"):
        run_json_worker(["worker.exe"], {}, cwd=tmp_path, timeout_seconds=5)


def test_run_json_worker_reports_malformed_json_decode_error(
    monkeypatch, tmp_path: Path
):
    def fake_run(command, **kwargs):
        return type(
            "Completed",
            (),
            {"returncode": 0, "stdout": "{not json", "stderr": ""},
        )()

    monkeypatch.setattr("private_search.osint.worker.subprocess.run", fake_run)

    with pytest.raises(WorkerExecutionError) as error:
        run_json_worker(["worker.exe"], {}, cwd=tmp_path, timeout_seconds=5)

    assert error.value.user_message == "worker produced invalid JSON"
    assert error.value.diagnostics == "{not json"


def test_run_json_worker_reports_non_zero_exit_with_bounded_diagnostics(
    monkeypatch, tmp_path: Path
):
    stderr = "x" * 3000

    def fake_run(command, **kwargs):
        return type(
            "Completed",
            (),
            {"returncode": 7, "stdout": "", "stderr": stderr},
        )()

    monkeypatch.setattr("private_search.osint.worker.subprocess.run", fake_run)

    with pytest.raises(WorkerExecutionError) as error:
        run_json_worker(["worker.exe"], {}, cwd=tmp_path, timeout_seconds=5)

    message = str(error.value)
    assert "code 7" in message
    assert "x" * 2000 in message
    assert "x" * 2001 not in message


def test_run_json_worker_keeps_startup_message_safe_and_bounds_os_error(
    monkeypatch, tmp_path: Path
):
    raw_detail = "[WinError 2] missing worker at C:\\private\\secret\\worker.exe"

    def fake_run(command, **kwargs):
        raise OSError(raw_detail)

    monkeypatch.setattr("private_search.osint.worker.subprocess.run", fake_run)

    with pytest.raises(WorkerExecutionError) as error:
        run_json_worker(["worker.exe"], {}, cwd=tmp_path, timeout_seconds=5)

    assert error.value.user_message == "could not start worker"
    assert error.value.diagnostics == raw_detail
    assert str(error.value) == f"could not start worker: {raw_detail}"


def test_run_json_worker_reports_timeout(monkeypatch, tmp_path: Path):
    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(cmd=command, timeout=11)

    monkeypatch.setattr("private_search.osint.worker.subprocess.run", fake_run)

    with pytest.raises(WorkerExecutionError, match="timed out"):
        run_json_worker(["worker.exe"], {}, cwd=tmp_path, timeout_seconds=11)


def test_streaming_worker_parses_progress_and_preserves_final_json(tmp_path: Path):
    events = []
    code = (
        "import sys; "
        "sys.stderr.write('THEIA_PROGRESS {\\\"phase\\\":\\\"scan\\\",\\\"message\\\":\\\"Scanning\\\",\\\"completed\\\":2,\\\"total\\\":3}\\n'); "
        "sys.stderr.write('diagnostic\\n'); sys.stderr.flush(); "
        "print('{\\\"ok\\\":true}', flush=True)"
    )

    result = run_streaming_json_worker(
        [sys.executable, "-c", code],
        {},
        cwd=tmp_path,
        timeout_seconds=10,
        on_progress=events.append,
    )

    assert result == {"ok": True}
    assert len(events) == 1
    assert events[0].phase == "scan"
    assert events[0].completed == 2


def test_streaming_worker_reports_timeout(tmp_path: Path):
    with pytest.raises(WorkerExecutionError, match="timed out"):
        run_streaming_json_worker(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            {},
            cwd=tmp_path,
            timeout_seconds=1,
        )
