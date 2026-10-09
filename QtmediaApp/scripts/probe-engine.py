"""Exercise the packaged JSONL engine without printing provider data."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    args = parser.parse_args()
    app = Path(__file__).resolve().parents[1]
    binary = app / "src-tauri/binaries/qtmedia-engine-x86_64-pc-windows-msvc.exe"
    env = {**os.environ, "QTMEDIA_FFMPEG": str(app / "src-tauri/binaries/ffmpeg-x86_64-pc-windows-msvc.exe")}
    requests = [
        {"id": "probe", "action": "probe"},
        {"id": "inspect", "action": "inspect", "url": args.url},
    ]
    with tempfile.TemporaryDirectory(prefix="qtmedia-probe-") as root:
        result = subprocess.run(
            [str(binary), "--library-root", root],
            input="\n".join(json.dumps(item) for item in requests) + "\n",
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, timeout=150,
        )
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
            print(json.dumps({key: event[key] for key in ("id", "event", "code", "formats") if key in event}))
        except (ValueError, TypeError):
            print(json.dumps({"non_protocol_stdout_bytes": len(line.encode())}))
    print(json.dumps({"exit_code": result.returncode, "stderr_bytes": len(result.stderr.encode())}))


if __name__ == "__main__":
    main()
