# QtmediaApp

QtmediaApp is the Tauri desktop interface for inspecting approved direct media
links, choosing a video resolution or MP3 download, and browsing a local media
library. It is independent from the terminal CLI in [`../Qtmedia`](../Qtmedia).

## Stack

- **Desktop shell:** Tauri 2 and Rust.
- **UI:** React, TypeScript, and Vite.
- **Download engine:** Python sidecar packaged with PyInstaller.
- **Communication:** JSON Lines over the local process stdin/stdout pipe; no
  localhost server.
- **Media:** FFmpeg/ffprobe, Video.js, and a native Rust audio engine.

## Setup

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

Build Windows installers with `pnpm desktop:build`. Generated binaries and
build output are ignored; rebuild the pinned runtimes and sidecar before a
clean release build.

## Checks

```bash
pytest -q sidecar/tests
pnpm --dir frontend test --run
pnpm --dir frontend build
cargo test --locked --manifest-path src-tauri/Cargo.toml
```

See [`setup.md`](setup.md) for the complete setup, architecture, and release
guide.
