from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_worker():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "private_search"
        / "osint"
        / "blackbird_worker.py"
    )
    spec = importlib.util.spec_from_file_location("theia_blackbird_worker_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_runtime_separates_request_and_operation_timeouts(monkeypatch, tmp_path: Path):
    worker = _load_worker()
    monkeypatch.setenv("PRIVATE_SEARCH_BLACKBIRD_TIMEOUT", "300")
    monkeypatch.setenv("PRIVATE_SEARCH_BLACKBIRD_REQUEST_TIMEOUT", "15")

    runtime = worker._build_runtime(root=tmp_path, workdir=tmp_path)

    assert runtime.timeout == 15
    assert runtime.operation_timeout == 290
