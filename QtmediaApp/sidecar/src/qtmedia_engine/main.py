"""Executable JSONL loop for the Qtmedia desktop engine."""

from __future__ import annotations

import argparse
import os
import sys
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO

from qtmedia.desktop_service.network import install_from_env as install_doh_from_env

from .engine import Engine
from .protocol import ProtocolError, encode_event, parse_request
from .ytdlp_update import Status, activate, tools_dir_from_env


def run(
    lines: Iterable[str],
    *,
    library_root: Path,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    ytdlp: Status | None = None,
    tools_dir: Path | None = None,
) -> int:
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    write_lock = threading.Lock()

    def emit(value: dict[str, object]) -> None:
        request_id = str(value.get("id") or "unknown")
        event = str(value.get("event") or "error")
        payload = {key: item for key, item in value.items() if key not in {"id", "event"}}
        encoded = encode_event(request_id, event, payload)
        with write_lock:
            output.write(encoded + "\n")
            output.flush()

    engine = Engine(library_root, emit=emit, ytdlp=ytdlp, tools_dir=tools_dir)
    try:
        for line in lines:
            if not line.strip():
                continue
            try:
                engine.handle(parse_request(line))
            except ProtocolError:
                emit({"id": "unknown", "event": "error", "code": "protocol_error"})
                errors.write("protocol_error\n")
                errors.flush()
    finally:
        engine.shutdown()
    return 0


def protect_protocol_stdout() -> TextIO:
    """Reserve the real stdout for protocol events and divert everything else.

    yt-dlp, FFmpeg children, and other libraries write to fd 1 directly; any
    stray line there would be rejected by the host as malformed protocol.
    """
    sys.stdout.flush()
    protocol = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return protocol


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--library-root", required=True, type=Path)
    args = parser.parse_args()
    protocol = protect_protocol_stdout()
    # Before anything imports yt_dlp: a verified, newer update replaces the
    # bundled copy (see ytdlp_update.py).
    tools_dir = tools_dir_from_env()
    ytdlp = activate(tools_dir)
    install_doh_from_env()
    return run(
        sys.stdin,
        library_root=args.library_root,
        stdout=protocol,
        ytdlp=ytdlp,
        tools_dir=tools_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
