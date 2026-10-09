from __future__ import annotations

from io import StringIO
from pathlib import Path

from qtmedia_engine.main import run


def test_run_processes_probe_and_sanitizes_protocol_errors(tmp_path: Path):
    stdout = StringIO()
    stderr = StringIO()

    code = run(
        ['{"id":"probe","action":"probe"}\n', '{"id":"bad","action":"shell"}\n'],
        library_root=tmp_path,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stdout.getvalue().splitlines() == [
        '{"id":"probe","event":"ready"}',
        '{"id":"unknown","event":"error","code":"protocol_error"}',
    ]
    assert stderr.getvalue() == "protocol_error\n"
