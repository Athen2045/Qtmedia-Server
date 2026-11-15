# Qtmedia

[![CI](https://github.com/Athen2045/Qtmedia-Server/actions/workflows/ci.yml/badge.svg?branch=Development)](https://github.com/Athen2045/Qtmedia-Server/actions/workflows/ci.yml)

Qtmedia is a local media downloader and player with two independent interfaces:

- **CLI** — search supported sources, inspect available formats, and download
  media from the terminal.
- **QtmediaApp** — a Tauri desktop app for direct-link downloads, local media
  playback, and browsing the resulting library.

Both use the Python download engine built around [yt-dlp](https://github.com/yt-dlp/yt-dlp).
The desktop app runs that engine as a packaged sidecar over JSON Lines on a
local process pipe; it does not run a localhost server.

## Tech stack

- **CLI and engine:** Python 3.11+, Typer, Rich, Requests, Beautiful Soup,
  RapidFuzz, Pillow, yt-dlp, and FFmpeg.
- **Desktop shell:** Tauri 2 and Rust.
- **Desktop UI:** React, TypeScript, and Vite.
- **Playback:** Video.js for video and a native Rust audio engine for music.
- **Packaging and tests:** PyInstaller, pnpm, pytest, Ruff, Vitest, and Cargo.

## Repository layout

```text
Qtmedia/                 CLI and Python download engine
QtmediaApp/frontend/     React + TypeScript UI
QtmediaApp/src-tauri/    Tauri/Rust host and native playback
QtmediaApp/sidecar/      Packaged Python desktop engine
.github/workflows/       CI configuration
```

## Setup

### CLI

Requirements: Python 3.11+, FFmpeg and `ffprobe` on `PATH`.

```bash
cd Qtmedia
python -m venv .venv
source .venv/bin/activate             # Windows: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Use it with:

```bash
qt search "title"
qt download https://example.com/media
```

### Desktop app

Requirements include Node.js, pnpm, Rust with the MSVC target, WebView2, and
the platform build tools.

From `QtmediaApp/` in PowerShell:

```powershell
./scripts/prepare-ffmpeg.ps1
./scripts/prepare-deno.ps1
./sidecar/build-sidecar.ps1
cd frontend
pnpm install --frozen-lockfile
pnpm desktop:dev
```

Build installers with `pnpm desktop:build`. Generated binaries and build
output are intentionally ignored; prepare the pinned FFmpeg/Deno runtimes and
rebuild the sidecar before a clean desktop build.

## Checks

```bash
ruff check Qtmedia QtmediaApp/sidecar
pytest -q Qtmedia/tests QtmediaApp/sidecar/tests
pnpm --dir QtmediaApp/frontend test --run
pnpm --dir QtmediaApp/frontend build
cargo test --locked --manifest-path QtmediaApp/src-tauri/Cargo.toml
git diff --check
```

See [Qtmedia/README.md](Qtmedia/README.md) for CLI details and
[QtmediaApp/setup.md](QtmediaApp/setup.md) for the full desktop setup and
architecture guide.
