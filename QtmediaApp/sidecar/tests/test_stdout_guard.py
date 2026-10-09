from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SIDECAR_SRC = Path(__file__).resolve().parents[1] / "src"

# Library output and FFmpeg children write to fd 1; only protocol may reach it.
NOISY_CHILD = rf"""
import os, subprocess, sys
sys.path.insert(0, {str(SIDECAR_SRC)!r})
from qtmedia_engine.main import protect_protocol_stdout
protocol = protect_protocol_stdout()
print("[download] 34.8% of 2.87MiB")
sys.stdout.flush()
os.write(1, b"raw fd write\n")
subprocess.run([sys.executable, "-c", "print('child process output')"], check=True)
protocol.write('{{"id":"p","event":"ready"}}\n')
protocol.flush()
"""


def test_protect_protocol_stdout_diverts_library_and_child_output_to_stderr():
    result = subprocess.run(
        [sys.executable, "-I", "-c", NOISY_CHILD],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    assert result.stdout.splitlines() == ['{"id":"p","event":"ready"}']
    assert "[download] 34.8%" in result.stderr
    assert "raw fd write" in result.stderr
    assert "child process output" in result.stderr
