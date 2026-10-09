# QtmediaApp

Privacy-focused desktop application for inspecting approved direct media links,
choosing an available video resolution or MP3 (192 kbps), downloading locally,
and browsing the resulting media library.

QtmediaApp uses Tauri 2, React/TypeScript, and a long-lived PyInstaller Python
sidecar over JSON Lines stdin/stdout. It does not expose a localhost server.
The existing `Qtmedia/` CLI remains independent from the desktop application.

Implemented in the first usable build:

- mockup-matched Home shell with five accessible navigation destinations;
- explicit desktop adapter policy for the seven original providers plus
  YouTube, with private-target rejection;
- grouped per-height MP4 and MP3 format selection, progress, cancellation, and
  local artwork;
- supplied Material Search, Home, Settings, Content Copy, Music, Video, and
  Folder icons with accessible labels;
- separate provider/network availability errors from local sidecar failures;
- private application-data library with Files filters, search, sorting, and
  validated OS open actions;
- Windows frameless controls and macOS native-titlebar configuration;
- MSI and NSIS Windows release packaging with reported payload sizes (no fixed size limit).

## Development

Follow [`setup.md`](setup.md) for prerequisites and architecture. After the
Python environment and frontend dependencies exist:

```powershell
./scripts/prepare-ffmpeg.ps1
./sidecar/build-sidecar.ps1
cd frontend
pnpm test --run
pnpm desktop:dev
```

Build Windows installers with `pnpm desktop:build`. Generated binaries and
build trees are intentionally ignored; prepare FFmpeg and rebuild the sidecar
before each clean Tauri build.

Before working in this directory, read `context.md`, then `agent.md`, then
`skill.md`. The context file must be updated after every meaningful change.
