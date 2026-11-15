# Qtmedia CLI

The Qtmedia CLI is the standalone terminal interface for searching supported
media sources, inspecting available formats, and downloading selected media.
It uses the same Python download engine that powers the desktop sidecar, while
keeping its commands and runtime data independent.

## Stack

Python 3.11+, Typer, Rich, Requests, Beautiful Soup, RapidFuzz, Pillow,
yt-dlp, and FFmpeg.

## Setup

Requirements: Python 3.11+, FFmpeg and `ffprobe` on `PATH`, and network access
to the configured sources.

```bash
cd Qtmedia
python -m venv .venv
source .venv/bin/activate             # Windows: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Install `.[impersonation]` when a permitted source requires browser
impersonation support.

## Use

```bash
qt search "title"
qt download https://example.com/media
```

The `qtmedia-search` and `qtmedia-download` aliases remain available for
scripts. On Windows, `main.bat` starts the interactive menu.

Runtime data stays under `var/downloads/` and `var/cache/`. Do not commit
downloaded media, cookies, credentials, or cache databases.

## Checks

```bash
ruff check .
pytest -q
python -m compileall -q src tests main.py benchmarks
```

See [`instructions.md`](instructions.md) for CLI workflow guidance and
[`context.md`](context.md) for current project state.
