# QtmediaApp Setup and Development Guide

**Status:** Approved base setup

**Verified:** 2026-08-26

**Audience:** Agents and developers working inside `QtmediaApp/`.

**Goal:** Build the first Windows and macOS Qtmedia desktop application with
Tauri 2, React/TypeScript, a packaged Python sidecar, an approved direct-link
download flow, and a local Files library.

This is the single operational guide for the base milestone. It consolidates
the approved design, research findings, implementation plan, development
workflow, security rules, performance rules, and release gates. The design
specification remains the authority for product decisions; this file explains
how to implement those decisions.

The approved YouTube and multi-format update is detailed in
docs/superpowers/specs/2026-08-26-qtmedia-youtube-multi-format-design.md and
implemented by docs/superpowers/plans/2026-08-26-qtmedia-youtube-multi-format.md.

## 1. Read this before changing code

At the start of every work session:

1. Read `QtmediaApp/agent.md`.
2. Read `QtmediaApp/context.md`.
3. Read this `QtmediaApp/setup.md`.
4. Read the relevant sections of:
   - `docs/superpowers/specs/2026-08-26-qtmedia-desktop-design.md` for approved product and privacy requirements;
   - `docs/research/2026-08-26-qtmediaapp-build-plan-research.md` for evidence and release research;
   - `docs/superpowers/plans/2026-08-26-qtmediaapp-base.md` for task order and file-level implementation steps.
5. Read the repository-root `agents.md` before touching shared `Qtmedia/`
   code.
6. Run `git status --short` and inspect only files relevant to the request.
7. State the current phase, intended change, and completion check before
   editing.

Do not start a later milestone because its folder or placeholder exists. The
base milestone is complete only when Home and Files work, the other three
destinations are honest coming-soon states, the existing CLI remains intact,
and the acceptance gates in this file pass.

## 2. Source authority and non-negotiable decisions

When documents disagree, use this order:

1. The approved desktop design specification.
2. This setup guide when it records an implementation constraint from that
   specification.
3. The research note for externally verified toolchain and release facts.
4. The implementation plan for task order and proposed file locations.
5. `QtmediaApp/context.md` for current state only; it may be stale.

The following decisions are already approved:

- Tauri 2 is the native host.
- React + TypeScript + Vite is the UI.
- A single long-lived Python `qtmedia-engine` sidecar is the download and
  inspection implementation.
- Tauri and Python communicate through newline-delimited JSON over the local
  process stdin/stdout pipe.
- No localhost HTTP server is used.
- `Qtmedia/` remains the standalone CLI.
- Home accepts direct `http` and `https` links only and uses an explicitly
  approved adapter registry.
- Home, Files, and download-location Settings are active. Video and Music are
  visible but deferred.
- The base release does not include Video.js, a music player, playlists,
  browser-cookie access, telemetry, cloud storage, file migration, or a
  multi-root library. Settings may switch the one active application-owned
  library without moving existing downloads.
- As of 2026-09-15 there is no fixed app size limit. Record artifact and runtime
  sizes for information; the former 140 MB and 150 MB gates no longer apply.

Useful primary references:

- [Tauri repository](https://github.com/tauri-apps/tauri)
- [create-tauri-app](https://github.com/tauri-apps/create-tauri-app)
- [tauri-action](https://github.com/tauri-apps/tauri-action)
- [Tauri v2 start guide](https://v2.tauri.app/start/)
- [Tauri v2 development guide](https://v2.tauri.app/develop/)
- [React Learn](https://react.dev/learn)
- [Python sidecar example](https://github.com/dieharders/example-tauri-v2-python-server-sidecar)

The Python sidecar example is a packaging and lifecycle reference only. It
uses a localhost FastAPI server, which is not approved for QtmediaApp.

## 3. Product and visual baseline

The app has five visible destinations in a keyboard-reachable left rail:

| Destination | Base behavior |
| --- | --- |
| Home | Paste a direct link, inspect it, choose Audio or Video, and download. |
| Video | Coming-soon state; no player yet. |
| Music | Coming-soon state; no Spotify-like player yet. |
| Files | Browse downloaded audio and video, filter, sort, and open items. |
| Settings | View, open, change, or restore the default download location. |

Match the supplied mockup using implementation, not a screenshot:

- near-black content canvas and a slightly lighter rail;
- light neutral icons with an obvious selected state;
- restrained blue-purple-pink accent for the QT MEDIA lockup and selected
  controls;
- one readable sans-serif UI family;
- visible focus, hover, disabled, loading, success, and error states;
- Home’s link field remains the visual center of the first-use experience;
- use local assets only; do not load fonts, icons, analytics, or UI assets from
  a CDN;
- motion is limited to state changes and progress feedback, generally
  150–250 ms; no decorative page-load choreography.

## 4. Toolchain and platform prerequisites

The current Windows environment was found to have Node, npm, pnpm, Python, and
FFmpeg, but Rust/Cargo, the Tauri CLI, and PyInstaller were missing. Verify
before installing anything:

```powershell
node --version
npm --version
pnpm --version
python --version
rustc --version
cargo --version
ffmpeg -version
ffprobe -version
pyinstaller --version
pnpm exec tauri --version
```

Target baseline:

| Tool | Baseline |
| --- | --- |
| Tauri runtime/CLI/API | 2.11.x family, locked after scaffold |
| Rust | Stable; MSVC target on Windows; native Apple target on macOS |
| Node.js | Current LTS; use the same major in local setup and CI |
| Package manager | pnpm |
| React | 19.2.x selected patch |
| Vite | Selected supported 8.x patch |
| TypeScript | Exact compatible patch after scaffold |
| Python | Exact 3.11+ patch shared by sidecar builders |
| PyInstaller | 6.22.x baseline, locked after the first build |
| FFmpeg | Pinned release/provider with recorded checksum; ship `ffmpeg` and `ffprobe` only |

Platform requirements:

- Windows: Rust MSVC toolchain, Visual Studio C++ build tools, WebView2
  runtime availability, and NSIS for the first installer.
- macOS: Xcode Command Line Tools, Rust, native arm64/x64 build environment,
  Developer ID credentials for direct distribution, `notarytool`, and
  `stapler`.

Do not silently install floating versions. Record missing tools and the
selected versions in `QtmediaApp/context.md` before changing dependencies.

## 5. Repository layout

Keep the desktop app isolated from the CLI:

```text
qtmedia/
├── Qtmedia/                         # existing standalone CLI
├── QtmediaApp/
│   ├── frontend/                    # React, TypeScript, Vite, Vitest
│   │   └── src/
│   │       ├── components/          # shell, rail, Home, Files, states
│   │       ├── lib/                 # typed Tauri bridge and state helpers
│   │       ├── types.ts
│   │       ├── App.tsx
│   │       └── app.css
│   ├── src-tauri/                   # Rust host and capabilities
│   │   ├── src/main.rs
│   │   ├── src/commands.rs
│   │   ├── src/sidecar.rs
│   │   ├── capabilities/default.json
│   │   └── tauri.conf.json
│   ├── sidecar/                     # packaged Python engine
│   │   ├── src/qtmedia_engine/
│   │   │   ├── main.py
│   │   │   ├── protocol.py
│   │   │   ├── session.py
│   │   │   ├── policy.py
│   │   │   ├── engine.py
│   │   │   └── library.py
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── qtmedia-engine.spec
│   ├── scripts/
│   │   ├── build-sidecar.ps1
│   │   ├── build-sidecar.sh
│   │   └── check-size.ps1
│   ├── tests/                       # release-layout fixtures
│   ├── agent.md
│   ├── context.md
│   ├── setup.md
│   └── README.md
└── docs/
```

Generated bundles, virtual environments, `node_modules`, media, cookies,
tokens, and private source responses must not be committed.

## 6. Architecture and deep module seams

Use a small number of deep modules: keep complexity behind narrow interfaces
so callers and tests do not learn provider, process, filesystem, or packaging
details.

### Frontend interface

React calls a typed Tauri bridge. It should know about commands, events, and
display-safe models, not Python arguments or filesystem internals.

```text
React UI → typed bridge → Tauri commands/events → sidecar protocol
```

### Tauri host interface

The Rust host owns window lifecycle, exactly one sidecar per app session,
validated library paths, OS open actions, and event forwarding. It must not
expose arbitrary shell execution.

### Sidecar interface

The sidecar owns URL policy, approved adapters, inspection, download jobs,
cleanup, FFmpeg invocation, and library scanning. Its process entry point is a
thin protocol loop around a deeper `Engine` module.

Recommended internal seams:

- `AdapterRegistry`: approved host → adapter selection.
- `Inspector`: validated source → display-safe inspection.
- `Downloader`: inspected media ID + kind → job events and local file.
- `LibraryScanner`: fixed root → safe `LibraryEntry` values.
- `PathPolicy`: relative path → confined local path.
- `SidecarSession`: opaque media/job catalog and expiry.

Do not expose all of these as frontend commands. They are internal seams that
keep the implementation testable and replaceable. The external protocol stays
small: `probe`, `inspect`, `download`, `cancel`, and `library_list`.

### Existing Qtmedia integration

Only explicit structured seams may be reused from `Qtmedia/`:

```text
Qtmedia/src/qtmedia/desktop_service/models.py
Qtmedia/src/qtmedia/desktop_service/inspection.py
Qtmedia/src/qtmedia/desktop_service/download.py
Qtmedia/tests/test_desktop_service.py
```

Do not call Rich/Typer presentation code, CLI global output paths, terminal
status printing, stdin cancellation, or unrelated runtime modules from the
desktop sidecar.

## 7. Sidecar protocol and lifecycle

The protocol is newline-delimited JSON. stdout is protocol-only; sanitized
diagnostics go to stderr. The frontend never receives media bytes through IPC.

Allowed requests:

```json
{"id":"request-1","action":"probe"}
{"id":"request-2","action":"inspect","url":"<active-memory-source>"}
{"id":"request-3","action":"download","media_id":"media-1","format_key":"format-opaque-key"}
{"id":"request-4","action":"cancel","job_id":"job-1"}
{"id":"request-5","action":"library_list"}
```

The source value above is a protocol placeholder, not a URL to persist or log.
Only the initial inspect request may contain a raw URL. All later messages use
opaque IDs.

Stable events:

- `ready`
- `inspection_started`
- `inspection_ready`
- `download_started`
- `download_progress`
- `download_completed`
- `cancellation_requested`
- `download_cancelled`
- `library_changed`
- `error`

Errors use stable codes such as `invalid_url`, `unsupported_source`,
`no_formats`, `provider_unavailable`, `protocol_error`,
`sidecar_unavailable`, `path_escape`, and `download_failed`. Never echo
provider URLs, cookies, raw exception text, or untrusted filenames in an error.

Lifecycle rules:

1. Tauri computes and owns the default root or loads one validated custom root.
2. Tauri starts one target-specific sidecar with the validated root.
3. Rust serializes writes to stdin and parses one JSON event per stdout line.
4. Tauri forwards typed events to the current window.
5. Shutdown stops accepting new work, finishes protocol reads, then terminates
   the child cleanly.
6. Startup recovery removes abandoned temporary and partial job files.

If a sidecar process needs a child FFmpeg process, process-group cleanup must
be tested on Windows and macOS. Do not assume terminating a PyInstaller
bootloader automatically terminates every child process.

## 8. Approved-adapter and download policy

Before any provider request or `yt-dlp` call:

1. Parse and normalize the input.
2. Allow only `http` or `https`.
3. Reject missing hosts, malformed input, localhost, private-network, and
   other disallowed targets.
4. Match the normalized host against the explicit approved adapter registry.
5. Reject unknown hosts; do not use a permissive generic fallback.
6. Inspect metadata without downloading the final output.
7. Expose only formats proven available by inspection.
8. Revalidate the selected media before downloading because provider URLs may
   expire.

Download rules:

- The desktop policy explicitly approves the seven existing Qtmedia adapters
  plus YouTube video pages; generic yt-dlp hosts remain rejected.
- Inspection returns one opaque `format_key` per available video height and one
  MP3 option when audio is available. Public options contain `kind`, `label`,
  `extension`, optional `height`, and optional `bitrate_kbps`; provider format
  IDs and media URLs remain in the in-memory session only.
- Audio is encoded as MP3 at 192 kbps. Video is merged to playable MP4.
- The sidecar reports provider/network extraction failures as
  `provider_unavailable`; this is distinct from an unavailable local engine.
- Output names are sanitized and collision-safe.
- All outputs resolve below the fixed library root.
- Partial output and FFmpeg intermediates stay under `temp/` until final
  validation.
- Artwork is optional and belongs under `artwork/`.
- Missing artwork is not a download failure.
- Cleanup runs on success, cancellation, failure, and startup recovery.

## 9. Filesystem and local library

Default root:

```text
<app-data>/Qtmedia/library/
├── audio/
├── video/
├── artwork/
└── temp/
```

The sidecar scans only `audio/` and `video/`. It excludes temporary files and
artwork-only files. The base Files view supports All/Audio/Video filters,
local display-name search, Recent/Name/Size sorting, Open file, and Open
library folder. It does not provide delete.

Settings stores the selected root in a versioned local preference below app
data. A folder picker selection resolves to `<selection>/Qtmedia/library/`,
unless the selection already is a `Qtmedia/library` directory. Switching waits
for active work, probes a replacement sidecar before replacing the current one,
and leaves existing files untouched. React receives no arbitrary filesystem
permission. If switching fails, the previous root and engine remain active.

Returned entries contain only:

- relative path;
- media type;
- extension;
- size;
- modified time;
- optional duration;
- optional relative artwork path.

`PathPolicy` must reject absolute paths, `..` traversal, symlink escapes, and
anything outside the fixed root. Rust revalidates every open-file path; never
trust a sidecar-returned absolute path.

## 10. Python performance and reliability rules

Use the Python performance skill as a measurement discipline:

- profile before optimizing with `cProfile`, `timeit`, and memory tooling;
- optimize hot paths, not rare code paths;
- use dict/set lookups for adapter and job catalogs;
- use generators for large directory scans where practical;
- avoid unnecessary copies of metadata and event payloads;
- batch filesystem work and avoid one subprocess per metadata field;
- cache only deterministic, privacy-safe computations;
- bound queues and concurrent downloads so memory use is predictable;
- keep provider/network waits separate from CPU-heavy FFmpeg work;
- record benchmark inputs without real private URLs or media.

The sidecar must remain clear first. Any optimization needs a before/after
measurement and a regression test for behavior, memory, or latency.

The Dataverse-specific patterns are not a QtmediaApp dependency. If a future
remote metadata module is introduced, carry forward only the general practices:
typed configuration, explicit timeouts, transient-error retries with
exponential backoff, bounded batch operations, explicit field selection, and
pagination. Do not add a Dataverse SDK or remote data service to the base
release.

## 11. React performance and motion rules

Follow React’s component, state, event-handler, and list-key guidance:

- derive simple values during render instead of synchronizing duplicate state
  through effects;
- keep interaction logic in event handlers;
- use stable keys from library entry identity, never array position;
- keep global listeners deduplicated and clean them up;
- avoid barrel imports and defer heavy future player modules;
- lazy-load Video/Music player code only when those milestones are approved;
- keep Files rendering bounded; add virtualization only after measured need;
- use `content-visibility` or pagination for unusually large libraries;
- use `startTransition` or deferred values only when profiling shows input
  contention;
- keep IPC payloads small and display-safe.

GSAP is not required for the base shell. Prefer CSS transitions for the rail,
focus, loading, and progress states. If a future interaction genuinely needs
GSAP:

- use `@gsap/react` and `useGSAP`;
- scope selectors to a component ref;
- use `contextSafe` for event-handler-created animations;
- revert/clean up animations on unmount or update;
- run GSAP only in client lifecycle code;
- do not animate during SSR or add decorative page-load sequences.

## 12. Persistence and SQL decision

The base Files index is rebuilt from the filesystem. Do not add SQLite or a
SQL plugin merely to avoid implementing a safe scan.

If a later milestone proves that a local index is necessary, apply the SQL
optimization rules before choosing a schema:

- select explicit columns; never use `SELECT *` in production paths;
- design indexes from measured query patterns and execution plans;
- use keyset/cursor pagination for large libraries rather than deep OFFSET;
- batch writes in transactions;
- use prepared statements;
- avoid N+1 queries and function-wrapped indexed columns;
- use realistic fixture sizes before claiming an improvement;
- monitor query time and index usefulness.

The persisted schema may contain only local media metadata. It must not contain
source URLs, cookies, provider request payloads, or remote response bodies.

## 13. Development sequence

Complete tasks in this order and stop at each exit gate:

### Phase 0 — preflight and size spike

- Verify and record tool versions.
- Scaffold the smallest Tauri React/TypeScript app.
- Build a probe Python sidecar with PyInstaller.
- Confirm target-suffixed sidecar naming and one JSONL round trip.
- Measure sidecar, FFmpeg, frontend, and host payloads.

Exit: the current target passes the probe and has a first artifact report.

### Phase 1 — Tauri/React shell

- Create the native window and minimal capabilities.
- Implement the rail and five routes.
- Make Home and Files active.
- Render explicit coming-soon states for Video and Music; activate Settings.

Exit: UI tests prove navigation, focus, responsive layout, and the visual
direction without network-loaded assets.

### Phase 2 — structured Qtmedia seam and sidecar

- Add typed inspection/download models without changing CLI commands.
- Implement strict protocol parsing and event encoding.
- Add adapter policy, opaque IDs, path confinement, cleanup, and library scan.
- Connect Rust to one long-lived sidecar.

Exit: protocol, policy, path, cleanup, Rust bridge, and existing CLI tests pass.

### Phase 3 — Home workflow

- Implement paste/clipboard input.
- Inspect approved links.
- Present proven Audio/Video choices.
- Show progress and cancellation.
- Refresh Files after completion.

Exit: fixture Audio and Video jobs complete below the fixed root; rejected
links never reach the downloader.

### Phase 4 — Files workflow

- Implement scan, filters, search, sorting, empty state, open file, and open
  folder.
- Keep delete, file migration, multiple simultaneous roots, and playlists deferred.

Exit: Files survives an index rebuild and rejects path escapes.

### Phase 5 — release packaging

- Build Windows x64, macOS arm64, and macOS x64 separately.
- Ship only the required FFmpeg tools.
- Run size, signing, notarization, and launch checks.

Exit: each target has a verified artifact with recorded size and the correct
platform release checks have passed.

## 14. Scaffold and daily commands

Use the official `create-tauri-app` React + TypeScript template after the
preflight. Keep the generated project in a temporary scaffold directory if
the existing `QtmediaApp/` documentation must be preserved, then normalize
the frontend into `QtmediaApp/frontend/` and keep `src-tauri/` at the app root.

Typical commands after scaffolding:

```powershell
pnpm install --dir QtmediaApp/frontend
pnpm --dir QtmediaApp/frontend dev
pnpm --dir QtmediaApp/frontend test --run
pnpm --dir QtmediaApp/frontend build
cargo check --manifest-path QtmediaApp/src-tauri/Cargo.toml
cargo test --manifest-path QtmediaApp/src-tauri/Cargo.toml
pytest QtmediaApp/sidecar/tests -q
pytest Qtmedia/tests -q
git diff --check
```

Run `pnpm tauri dev` from the generated Tauri project root after the scaffold
has been normalized. The exact script and config path should follow the
generated package scripts; do not invent a second package manager or duplicate
lockfile.

## 15. Tests and acceptance gates

Required focused tests:

- sidecar probe, malformed JSON, unknown action, event sanitization;
- approved adapter selection and private-network rejection;
- opaque media/job expiry and invalid state transitions;
- output-name sanitization and fixed-root path confinement;
- symlink escape rejection;
- cancellation and startup cleanup;
- library scanning and deterministic filters/sorting;
- Rust sidecar exit and malformed-output handling;
- React navigation, Home states, clipboard gesture, and Files states.

Before claiming the base milestone:

```powershell
pytest Qtmedia/tests -q
pytest QtmediaApp/sidecar/tests QtmediaApp/tests -q
pnpm --dir QtmediaApp/frontend test --run
pnpm --dir QtmediaApp/frontend build
cargo test --manifest-path QtmediaApp/src-tauri/Cargo.toml
git diff --check
```

Acceptance also requires that:

- raw source URLs do not appear in protocol events, logs, preferences,
  filenames, or Files entries;
- rejected links do not reach `yt-dlp`;
- media bytes never cross the UI bridge;
- partial files are cleaned after success, cancellation, failure, and restart;
- CLI behavior remains unchanged;
- Home and Files are usable, and other routes clearly communicate deferral.

## 16. Packaging, size, and release

Build native target-specific sidecars:

| Artifact | Target | Package |
| --- | --- | --- |
| Windows x64 | `x86_64-pc-windows-msvc` | NSIS `.exe` first; MSI later if needed |
| macOS arm64 | `aarch64-apple-darwin` | DMG |
| macOS x64 | `x86_64-apple-darwin` | DMG |

Use the required target suffix for each external binary. Do not build a
universal macOS package until measurements show it remains safe.

Measure both compressed installer/DMG size and installed payload size.
There is no fixed size ceiling following the user's 2026-09-15 decision.
Include dependencies needed for reliable inspection, conversion, and playback;
avoid unnecessary duplication and record notable size changes.

Release rules:

- pin and checksum FFmpeg provenance;
- exclude `ffplay` and unused resources;
- use Tauri release optimization settings supported by the locked Rust tool;
- run `tauri-action` on native Windows and macOS runners;
- sign Windows executables/installers with Authenticode;
- sign, notarize, and staple macOS direct-distribution artifacts;
- keep signing credentials out of source, logs, and artifacts;
- publish only after tests, size checks, and launch/probe checks pass.

## 17. Deferred work

Do not implement these in the base milestone:

- embedded Video.js player;
- Spotify-like music player, playlists, or background artwork workflow;
- title search or Spotify matching;
- additional provider adapters beyond the approved registry;
- browser cookies or account authentication;
- library deletion, automatic migration, or multiple simultaneous library roots;
- telemetry, cloud synchronization, remote accounts, or a localhost API;
- SQLite/SQL persistence without measured need;
- GSAP or other animation dependencies without a concrete interaction need;
- Dataverse or any remote business-data SDK.

When a deferred feature is started, update the design specification, research,
plan, this setup guide, and `QtmediaApp/context.md` before implementation.

## 18. Context maintenance and completion report

After every meaningful session, update `QtmediaApp/context.md` with:

- verification date;
- current phase;
- completed work;
- next concrete action;
- open decisions or blockers;
- changed files;
- verification results and what remains unverified.

The final report for a task must state what changed, which focused checks ran,
which platform-specific checks did not run locally, and whether the size and
privacy gates were applicable.

## Skill application record

This guide was consolidated using:

- Python performance profiling and optimization guidance;
- Dataverse advanced reliability patterns, applied only as general typed
  timeout/retry/batching guidance and not as a dependency;
- Tauri architecture, setup, sidecar, process, shell, capability, and release
  guidance;
- SQL query/index/pagination guidance, applied only to a possible future local
  index;
- GSAP React scoping and cleanup guidance, with CSS preferred for the base UI;
- React performance guidance for bundle size, state, effects, lists, and
  re-render control;
- Diátaxis documentation principles;
- codebase-design vocabulary for deep modules, interfaces, seams, adapters,
  leverage, locality, and test surfaces.
