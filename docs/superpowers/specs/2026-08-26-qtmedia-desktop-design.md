# Qtmedia Desktop Base Application Design

**Status:** Approved in chat on 2026-08-26; awaiting written-spec review

**Goal:** Add a privacy-focused Tauri desktop application for Windows and
macOS whose first usable milestone makes the Home link workflow and local
Files library reliable, while preserving the existing Qtmedia CLI and leaving
the Video, Music, and Settings destinations ready for later milestones.

**Reference:** The user-provided `Home.png` mockup and the supplied
SpotiFLAC 7.2.2 archive are visual and architectural references only. The
SpotiFLAC backend, provider logic, account workarounds, and assets are not
copied into Qtmedia. The upstream repository is MIT-licensed, but this design
uses its Wails/React desktop shape only as inspiration.

## 1. Product scope

The base release contains one focused desktop application with five visible
destinations:

| Destination | Base behavior |
| --- | --- |
| Home | Paste a direct media link, validate an approved adapter, inspect it, choose Audio or Video, and download it. |
| Video | Visible navigation destination with a consistent coming-soon state; player implementation is deferred. |
| Music | Visible navigation destination with a consistent coming-soon state; music-player implementation is deferred. |
| Files | Browse downloaded audio and video files, filter them, inspect basic details, open a file with the operating system, and open the library folder. |
| Settings | Visible navigation destination with a consistent coming-soon state; settings behavior is deferred. |

The base release does not implement a search-by-title experience. “Search” in
the base product means inspecting the link pasted into the Home field. It does
not import SpotiFLAC's Spotify matching or third-party music-provider logic.

The base release also does not implement an embedded video or music player.
The Files model and media-type metadata must be shaped so those players can be
added without changing the download protocol or moving user files.

## 2. Design language

The interface follows the supplied mockup rather than reproducing it as a
static image:

- near-black content surface with a slightly lighter navigation rail;
- light neutral icons with a clear active state;
- restrained blue-purple-pink branding accent used for the QT MEDIA lockup
  and selected states only;
- one primary sans-serif UI family, with no display face used for controls;
- compact, familiar controls with visible focus, hover, disabled, loading,
  success, and error states;
- no decorative page-load animation; motion is limited to state changes and
  progress feedback;
- the Home view keeps the link field as the visual center of the first-use
  experience;
- the Files view uses a practical list/grid toggle only if both layouts remain
  equally understandable; the first implementation may use a list layout
  exclusively.

The navigation rail is keyboard reachable. Each icon has an accessible name
and tooltip. Home and Files are active destinations in the base release. The
other destinations render a non-interactive or clearly disabled “Coming next”
state instead of silently doing nothing.

## 3. Runtime architecture

```text
React + TypeScript UI
        |
        | Tauri commands/events
        v
Tauri 2 Rust host
        |
        | stdin/stdout JSON Lines, no listening localhost server
        v
qtmedia-engine Python sidecar
        |
        | existing Qtmedia inspection/download modules
        v
approved adapters + yt-dlp + FFmpeg
        |
        v
private application media library
```

### Tauri host

The Tauri host owns:

- window lifecycle and native dialogs;
- starting and stopping exactly one authenticated sidecar process per app
  session;
- the allowlisted sidecar command and its capability configuration;
- opening a selected local file or the library folder through the operating
  system;
- forwarding structured sidecar events to React;
- app-level preferences that do not contain source URLs.

The host must not expose an arbitrary shell command to the frontend. Tauri
capabilities allow only the named `qtmedia-engine` sidecar and the specific
open-file/open-folder operation required by the Files view.

### Python sidecar

The sidecar is a platform-specific PyInstaller executable built from an
application-owned desktop service package. It may consume stable Qtmedia
inspection and transfer primitives, but it must not call the existing
interactive CLI functions unchanged. In particular, the sidecar must not
depend on Rich output, global CLI output paths, stdin cancellation, or printed
status text.

The existing `qtmedia` CLI entry points remain independently usable. Any
structured inspection/download seam added for the desktop must be callable
without changing the CLI's command names or terminal behavior.

The sidecar uses an ephemeral in-memory job catalog. It stores the validated
source URL only while the current app session needs it and addresses it with
an opaque media/job ID in all later UI messages.

## 4. Sidecar protocol

The protocol is newline-delimited JSON. stdout is protocol-only. Diagnostic
messages go to stderr and are sanitized before display or logging.

Requests from Tauri to the sidecar have this shape:

```json
{"id":"request-1","action":"inspect","url":"https://source.example/video/abc"}
{"id":"request-2","action":"download","media_id":"media-1","kind":"audio"}
{"id":"request-3","action":"cancel","job_id":"job-1"}
{"id":"request-4","action":"library_list"}
```

The URL is accepted only in the initial inspect request. It must never appear
in a response event, UI log, persistent preference, filename, or error text.

Inspection responses expose only display-safe and selection-safe data:

```json
{
  "id":"request-1",
  "event":"inspection_ready",
  "media_id":"media-1",
  "site":"Approved adapter",
  "title":"Display title",
  "duration_seconds":123,
  "options":[
    {"key":"video","label":"Video","extension":"mp4"},
    {"key":"audio","label":"Audio","extension":"mp3"}
  ]
}
```

The sidecar emits stable events for `inspection_started`,
`inspection_ready`, `download_started`, `download_progress`,
`download_completed`, `download_cancelled`, `library_changed`, and
`error`. Progress is numeric and includes downloaded bytes, total bytes when
known, and a bounded percentage when a total exists.

The sidecar must reject malformed JSON, unknown actions, unknown media/job
IDs, expired in-memory entries, and download requests that do not match the
most recent inspection catalog.

## 5. Approved-adapter and download policy

Home accepts direct `http` and `https` links only. Before yt-dlp or any
provider-specific request runs, the sidecar must:

1. parse and normalize the URL;
2. reject unsupported schemes, missing hosts, malformed URLs, and local or
   private-network targets;
3. resolve the host against the explicitly approved Qtmedia adapter registry;
4. reject unknown hosts instead of using the current CLI's permissive generic
   fallback;
5. inspect metadata without downloading the final output;
6. expose only `Audio` and/or `Video` options that the inspection proves are
   available and processable;
7. revalidate the selected media before downloading because provider URLs can
   expire.

The first user-facing output choices are:

- `Video`: merge/select a playable MP4 output when the source and FFmpeg make
  that possible;
- `Audio`: extract an audio output using the sidecar's configured default
  audio codec.

The exact codec/quality catalog remains provider-driven. The UI must not
promise a quality that inspection did not expose. If inspection provides a
thumbnail or artwork URL, the sidecar may download a local copy during the
download job into the artwork area; missing artwork is not a download failure.

Each download gets an opaque random job ID and writes below a fixed library
root. Output names are sanitized, collision-safe, and never derived from a
raw path supplied by the UI. Partial files and FFmpeg intermediates remain in
the temporary area until the final output is validated, then are removed.

## 6. Local library and Files view

The default library is inside the operating-system application-data location:

```text
<app-data>/Qtmedia/library/
├── audio/
├── video/
├── artwork/
└── temp/
```

The library root is passed to the sidecar by Tauri at startup. It is not
accepted from an untrusted sidecar response. A future Settings milestone may
allow the user to move this root; the base release exposes the default root
and an “Open library folder” action.

The Files view scans only the fixed library root and displays media files from
`audio/` and `video/`. It excludes temporary files and artwork-only files.
Each row includes:

- display name;
- audio/video type;
- extension;
- file size;
- modified time;
- optional duration if it can be read without a full media decode.

Base actions are:

- filter by All, Audio, or Video;
- search by local display name;
- sort by recent, name, or size;
- open the file with the operating system;
- open the library folder.

The base release does not add a destructive delete action. Cleanup is limited
to temporary and incomplete job files owned by the app.

The library index may be rebuilt from the filesystem. If a small local index
is introduced for performance, it may contain only relative path, media type,
size, timestamps, duration, and artwork path. It must not contain source URLs,
cookies, request payloads, or remote provider metadata.

## 7. Home view states

The Home screen has explicit states:

1. **Empty:** branding, link field, clipboard action, and concise instruction.
2. **Inspecting:** disabled submit control, skeleton result area, and a cancel
   action that stops the inspection request.
3. **Ready:** adapter name, safe display metadata, Audio/Video choices, and a
   single download action for the selected choice.
4. **Downloading:** current file name, byte progress when available, status,
   cancel action, and no fabricated speed or completion percentage.
5. **Completed:** success state, open Files action, and open library-folder
   action.
6. **Rejected/error:** short user-facing reason such as unsupported link,
   no compatible output, or temporary source failure; internal details remain
   sanitized and code-based.

The Home page never displays the raw source URL after submission. The input
may remain in the local component state while the current request is active,
but it is cleared when the job completes, fails, or the app session ends.

## 8. Privacy and security

- No telemetry, analytics, remote account, or cloud media library is part of
  the base release.
- Raw URLs exist only in active process memory and the local sidecar pipe.
- Raw URLs, cookies, thumbnails, titles, and source responses are not written
  to logs or persistent app preferences.
- Browser cookies are not read by the desktop app in the base release.
- The sidecar has no listening HTTP port.
- Tauri's shell capability is restricted to the named sidecar and validated
  arguments.
- Library paths are resolved under the library root before creating or
  removing files; symlink escapes are rejected.
- Temporary files are removed after successful finalization, cancellation,
  failure, and startup recovery of abandoned jobs.
- The UI includes a short local-processing/privacy notice and a reminder to
  download only media the user has permission to access.

These desktop rules are additive to the repository's existing Telegram design.
They do not move Telegram runtime data, change its transport, or make the
Telegram bot depend on the desktop app.

## 9. Proposed repository layout

```text
qtmedia/
├── Qtmedia/                         # existing standalone CLI
│   └── src/qtmedia/                  # reusable inspection/transfer primitives
├── QTmediaBot/                       # existing standalone Telegram bot
├── QTmediaDesktop/                   # new Tauri desktop application
│   ├── frontend/                     # React + TypeScript UI
│   ├── src-tauri/                    # Rust host, capabilities, packaging
│   ├── sidecar/                      # desktop JSONL service and PyInstaller spec
│   ├── tests/                        # UI/protocol/packaging-focused tests
│   └── README.md                     # desktop development and release guide
└── docs/superpowers/specs/           # workspace design and implementation docs
```

The desktop package owns its UI and protocol service. The existing CLI package
owns command-line presentation. Shared Python code is limited to explicit,
tested inspection and transfer primitives; no shared Telegram runtime or
desktop UI code is introduced.

## 10. Verification and acceptance gates

The base milestone is accepted when all of the following are true:

- Home accepts a valid approved-adapter URL and rejects an unknown host before
  the downloader runs.
- Inspection returns only display-safe metadata and valid Audio/Video choices.
- A selected format produces a completed file below the fixed library root.
- Progress, cancellation, failure, and completion events render correctly.
- Temporary and partial files are removed after terminal job states.
- Files lists audio and video files from the library and excludes temp/artwork
  internals.
- Open-file and open-folder actions resolve only validated local paths.
- The five-item navigation is visible, keyboard reachable, and consistent;
  Home and Files work, while Video, Music, and Settings have an honest
  coming-soon state.
- The existing Qtmedia CLI test suite remains passing and its command behavior
  is unchanged.
- Sidecar protocol tests prove raw URLs do not appear in response payloads or
  sanitized diagnostic output.
- A Windows and macOS packaging smoke check produces the expected Tauri app
  bundle/installer shape with the matching Python sidecar target.

## 11. Deferred milestones

After the base Home/Files release is stable:

1. add the embedded Video player and video-library playback actions;
2. add the Music player, local artwork/poster handling, playlists, and music
   library views;
3. add Settings for library relocation, defaults, and adapter diagnostics;
4. add code signing, notarization, update delivery, and release automation;
5. add more provider adapters only after each adapter has an explicit policy
   review and focused tests.
