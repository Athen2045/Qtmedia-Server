# QtmediaApp Context Snapshot

**Last reviewed:** 2026-10-09

**Current phase:** Bare-minimum operational build verified in the real release
app on branch `Development` and ready for its first commit. The
2026-10-09 pass found and fixed the cause of the "lost media engine": yt-dlp's
console progress bar corrupted the JSONL stdout pipe on the first download.
Home, Files, and Settings are active. Video and Music remain intentional
coming-soon sections; macOS packaging is deferred at the user's request.

## 2026-10-09 operational pass

Root cause of the engine loss: with `quiet` alone, yt-dlp still printed
`[download] NN%` bars to stdout, gluing them onto protocol lines. The Rust host
treats any unparseable stdout line as a dead engine and killed it on the first
download. Fixes:

- `download.py`: `noprogress: True` for desktop downloads.
- `qtmedia_engine/main.py`: `protect_protocol_stdout()` keeps a private dup of
  fd 1 for protocol events and points fd 1 and `sys.stdout` at stderr, so
  library prints and FFmpeg children can never reach the pipe.
- `sidecar.rs`: whitespace-only stdout lines are ignored rather than fatal.
- Cancel reported `download_failed` and left fragment files: yt-dlp wraps the
  hook's cancellation in `DownloadError`, and fragment threads still held
  `.part` files, so cleanup raised `PermissionError` from `finally`. Cancellation
  is now recognized through the wrapper, and cleanup retries locked files for
  ~3 s and never masks the job outcome.

Verification (2026-10-09):

- Packaged engine driven over JSONL with `https://youtu.be/XbNIT-6_0bU`
  (3:01): 1440p–144p plus MP3 listed; 720p (960×720 VP9/AAC MP4), 1440p, and
  MP3 completed with artwork; zero non-JSON stdout lines (525 before the fix).
- Real release `Qtmedia.exe` driven through its WebView2 DevTools port: inspect,
  720p download with navigation to Files mid-job (tray stays visible), Files
  auto-refresh with artwork, MP3 download, 1440p cancel showing "Download
  cancelled.", re-inspect after cancel, Settings path display. Force-closing
  the host left no orphaned engine processes.
- Suites: sidecar 25 passed (needs `PYTHONPATH=QtmediaApp/sidecar/src`);
  shared Qtmedia 120 passed + 1 machine-dependent CLI failure
  (`test_ydl_options_uses_opt_in_firefox_cookies_for_spankbang` sees a real
  local Firefox profile); Rust 23 passed, `cargo fmt --check` clean; Vitest 30
  passed (no frontend change).
- Not verified: NSIS/MSI installer rebuild. Bundling timed out downloading the
  NSIS/WiX toolsets from GitHub in the agent sandbox; `target/release/Qtmedia.exe`
  with its sibling engine and FFmpeg was rebuilt and tested instead.

Known gaps carried forward:

- After a cancel, one `.part` file written late by a fragment thread can remain
  in `temp/` until the next engine start sweeps it.
- YouTube heights are delivered as VP9-in-MP4; most players handle it, but some
  default Windows players may need the VP9 extension.
- `scripts/prepare-ffmpeg.ps1` copies whatever FFmpeg is on PATH; no pinned
  version/checksum and no `ffprobe` yet.
- `tauri.conf.json` `targets: "all"` also builds MSI (WiX); use
  `pnpm desktop:build --bundles nsis` for the NSIS-only release.

Changed files: `Qtmedia/src/qtmedia/desktop_service/download.py`,
`Qtmedia/tests/test_desktop_service.py`,
`sidecar/src/qtmedia_engine/main.py`, `sidecar/tests/test_stdout_guard.py`,
`src-tauri/src/sidecar.rs`, and this context.

## Current product behavior

- Home follows the approved 2026-09-14 visual direction: compact Q navigation
  rail, centered QT MEDIA lockup, “Save media. Keep it yours.” introduction,
  and a focused direct-link field. The former “Save to your Qtmedia Library”
  storage strip is removed.
- Inspection opens an accessible top-down format panel. Exact discovered video
  heights and MP3 192 kbps are selectable; the desktop download path does not
  silently replace the chosen video format with a generic best format.
- The active download session survives navigation. A global activity tray shows
  truthful byte/percentage data when the provider supplies it, keeps
  “Cancelling…” visible while cleanup is running, and refreshes Files after a
  completed job.
- Files provides loading, load-failure/retry, empty-library, no-filter-match,
  search, filter, sort, artwork, and validated open actions.
- Settings displays the full active download location. A native folder picker
  can switch to `<selected folder>/Qtmedia/library`, or recognize a selected
  existing `Qtmedia/library`; “Use default” restores the platform app-data
  location. The versioned preference persists locally. Existing media is not
  moved, and switching is rejected while inspection/download/cancellation is
  active. The replacement sidecar is probed before the old engine is stopped.

## Architecture and privacy boundaries

Tauri 2.11.5 owns the window, application-data root, settings preference,
sidecar lifecycle, request correlation, path validation, confined artwork
reads, and OS open operations. React 19.2.8/Vite renders the interface. One
long-lived PyInstaller `qtmedia-engine` process communicates through JSON Lines
on stdin/stdout; no Python localhost server is used.

The desktop service remains separate from the CLI-facing download function.
The current explicit desktop policy covers the seven original providers plus
YouTube. Inspection sessions and provider selectors are opaque and in memory.
Raw URLs are accepted only by `inspect` and are not returned or persisted.
Rust capabilities expose neither arbitrary shell access nor unrestricted
frontend opener permissions. Artwork uses a bounded Rust data-URL transport
allowed by the narrow CSP.

Library layout:

```text
<active root>/
├── audio/
├── video/
├── artwork/
└── temp/
```

## Windows release result

The refreshed PyInstaller engine and Windows x64 NSIS installer were built on
2026-09-15. The final installer is:

`src-tauri/target/release/bundle/nsis/Qtmedia_0.1.0_x64-setup.exe`

- installer: 50.06 MiB / 52.50 MB;
- Tauri host: 11.50 MiB / 12.06 MB;
- Python engine: 21.39 MiB / 22.43 MB;
- FFmpeg: 98.09 MiB / 102.86 MB;
- runtime component subtotal: 130.98 MiB / 137.34 MB.

The installer and measured runtime subtotal are below the 140 MB internal
ceiling and the 150 MB product limit. This subtotal is not a measurement of
every byte added by an installed Windows WebView runtime if the target machine
does not already provide it.

## Verification on 2026-09-15

- shared/existing Qtmedia Python suite: 119 passed;
- sidecar Python suite: 23 passed;
- React/Vitest suite: 29 passed;
- Rust suite: 23 integration tests passed;
- production Vite build and optimized Tauri/NSIS build passed;
- rebuilt packaged sidecar probe returned protocol-only `ready`;
- focused RED/GREEN coverage exists for settings persistence/path selection,
  sidecar activity and intentional shutdown, exact provider selectors,
  cancellation acknowledgement, navigation-persistent progress, Settings retry,
  Files refresh/error states, and CSP artwork transport;
- capability tests confirm no frontend shell or unrestricted opener access.

The approved Home and Settings direction was visually inspected in the local
app/browser during implementation. Native picker selection/reset and exact
960×640/1024×640 window rendering still need a final manual installed-app pass.

## 2026-09-15 media-engine recovery fix

- Reproduced the reported state at the process boundary: the installed Tauri
  host was running while no `qtmedia-engine` process remained, so Find Formats
  had only a dead manager and returned `sidecar_unavailable`.
- Verified that the installed engine binary, installed FFmpeg, custom library
  root, redirected stdin/stdout protocol, probe, and an inspection request all
  worked independently. A clean host restart also spawned and retained the
  expected PyInstaller parent/child engine processes. Stopping an old engine
  while a separately probed replacement was active did not terminate the
  replacement. The original child-termination trigger was therefore not
  reproduced.
- Fixed the persistent failure mode in Rust: `inspect` and `library_list` now
  restart, probe, atomically install, and retry against one replacement engine
  after `sidecar_unavailable` or `sidecar_exited`. Download and cancel requests
  are never replayed because their opaque in-memory job state may be lost.
- Process failure now clears stale activity state, terminates a malformed or
  failed child, and avoids emitting a premature global error while a pending
  command is eligible for recovery.
- Added RED/GREEN recovery-policy and lost-activity tests. The complete Rust
  suite passed with 23 tests, formatting passed, the production frontend built,
  and a fresh NSIS installer completed at 52,503,523 bytes (52.50 MB).
- Changed files: `src-tauri/src/commands.rs`, `src-tauri/src/sidecar.rs`,
  `src-tauri/tests/sidecar_path.rs`, `setup.md`, and this context. The remaining
  check is to install the rebuilt NSIS package, reproduce an engine loss or the
  original user flow, and confirm Find Formats transparently recovers.

## Next concrete action

Commit the operational app (user-approved scope), then rebuild the NSIS
installer outside the sandbox with `pnpm desktop:build --bundles nsis`. The
2026-10-09 automated pass covered inspection, download, cancel, navigation, and
Files; the remaining manual items from the earlier list are:

1. In Settings, select a temporary custom parent folder, confirm the derived
   Qtmedia library path, open it, then restore the default location.
2. Inspect an authorized YouTube URL, confirm the listed heights, download one
   video and one MP3, cancel one test job, and navigate during another job.
3. Confirm Files refreshes automatically and opens only the selected active
   library's local media.
4. Check Home, Files, and Settings at 1366×768, 1024×640, and 960×640.

After that validation, the next product milestone is either the Video player or
Music library/player. macOS builds, signing, and notarization remain deferred.

## Known blockers and decisions

- Earlier agent-run YouTube extraction on this Windows host reached policy but
  failed before extraction with WinError 10013. Restricted agent networking
  means this does not prove an installed-app firewall problem; reproduce in the
  new build before prescribing endpoint-security changes.
- New CLI adapters are not automatically trusted by the desktop app. Add each
  one explicitly to the desktop policy after reviewing its URL/path rules.
- Switching download locations does not migrate old media in this version.
- Apple signing/notarization and Windows code signing require external
  credentials.

## Relevant implementation

- `frontend/src/lib/DesktopSession.tsx` and `frontend/src/components/` — shared
  workflow state, Home, Files, Settings, navigation, activity tray, and tests.
- `src-tauri/src/settings.rs`, `commands.rs`, `sidecar.rs`, `paths.rs`, and
  `protocol.rs` — preference, safe root switching, process lifecycle, and IPC.
- `sidecar/src/qtmedia_engine/` — JSONL engine and cancellation lifecycle.
- `../Qtmedia/src/qtmedia/desktop_service/` — structured inspection/download
  service used by the desktop sidecar; CLI entry points remain unchanged.
- `design/2026-09-14/` — approved mockups and design decisions.
- `../docs/superpowers/plans/2026-09-14-qtmedia-improved-workflow.md` —
  implementation plan followed for this pass.

## Files changed in this pass

- React application shell, Home, Files, Settings, shared session/activity UI,
  bridge types, CSS, and component tests under `frontend/`.
- Rust settings, commands, sidecar lifecycle, protocol, paths, capabilities,
  Tauri configuration, Cargo manifest/lockfile, and tests under `src-tauri/`.
- Python sidecar engine/tests and shared desktop inspection/tests.
- `setup.md`, approved Settings design, implementation plan, and this context.
- Rebuilt ignored release artifacts and target-suffixed sidecar binary.

Unrelated root documentation edits and the user's Telegram bot removals were
preserved and not modified as part of this app work.

## Maintenance rule

Read this file first and update it after every meaningful work session or
change affecting scope, architecture, dependencies, file layout, tests,
verification, blockers, or the next action.
