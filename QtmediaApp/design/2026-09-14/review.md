# Qtmedia: design review and three mockups

Date: 2026-09-14. Status: proposals, not implemented UI.

## Product direction

Qtmedia is a private, local-first desktop media library: paste an approved
source link, inspect the formats actually available, choose one, download into
application-owned storage, and find or open the saved file. Video playback and
a Spotify-like local music library are later destinations, not streaming-service
integrations. Windows comes first; macOS release work remains deferred.

Keep the existing Tauri/React/Python architecture, JSONL pipe, explicit desktop
adapter policy, URL-free persisted data, and filesystem library. The CLI remains
independent. The current source physically places the shared desktop service in
`Qtmedia/src/qtmedia/desktop_service/`; do not confuse logical independence with
a completed package relocation.

Review basis: application and repository context/guides, desktop setup and skill
registry, architecture, desktop/base and YouTube multi-format specifications and
plans, build research, and the core React, Rust bridge, Python inspection,
download, and sidecar paths. This is a focused product/source review, not an
exhaustive audit of every repository file or a live download test.

## The mockups

Open [the gallery](index.html) or the individual images:

1. [Home](01-home.png): keep the recognizable dark canvas and serif gradient
   wordmark. Explain the next action in one sentence. Give the input one clear
   primary action, a paste button, supported-source help, and a storage shortcut.
2. [Formats](02-formats.png): reveal a single panel below the link field, with
   source/title/duration, mutually exclusive video and audio rows, and one
   download button naming the selection. Keep the most common choices visible;
   expand additional available qualities instead of showing an overwhelming list.
3. [Files](03-files.png): promote the library into a readable table with local
   artwork, filter/search/sort controls, an obvious Open action, and persistent
   download activity while browsing.

All media names, thumbnails, sizes, dates, and progress values are fictional
sample data. These are generated visual concepts, not screenshots of implemented
features. Rail widths, exact SVG shapes, brand positioning, and typography are
approximate. Use the supplied local SVG paths and bundled font when implementing.
Do not copy incidental extra slogans, external-link glyphs, or undefined ellipsis
menus from the renders. Supported sites should open local help, not navigate away.

Inspection artwork, saved resolution/bitrate labels in Files, per-file Show in
folder, and the persistent activity tray are proposed extensions. The current
bridge does not provide all of those fields/actions. Add safe local metadata or
omit unavailable details; never infer them from filenames or fabricate them.

## Recommended visual specification

- Retain the 88 px rail, five destinations, and Windows custom controls. Mark
  Video, Music, and Settings as coming soon; do not make them look broken.
- Keep the near-black background, slightly lighter surfaces, and one violet
  interaction accent. Reserve the blue-to-pink gradient primarily for the brand.
- Use the serif only for the wordmark and the platform sans-serif for controls.
  Increase muted copy contrast; supporting text must remain readable.
- Keep a roughly 720 px input on the idle screen. Animate the result panel
  downward over 180–220 ms; honor reduced motion. No new animation dependency.
- Compact the brand area while inspecting/downloading so the panel fits at
  960×640. Use an independently scrollable options area with an always-reachable
  action footer. Do not allow the window chrome to scroll away.
- Use native radio semantics, visible keyboard focus, labels for icon buttons,
  and at least 44 px comfortable row targets. Announce status changes politely,
  without announcing every progress tick.
- Show only inspected choices. Display 480p if that is the source height, not
  a hard-coded 460p. Never promise 2160p or any other unavailable resolution.
- Keep link inspection and download as explicit separate actions. Clear the raw
  URL after terminal inspection, retaining safe title/source and a New link action.

## Highest-impact improvements, grounded in current code

| Priority | Finding | Recommended change |
| --- | --- | --- |
| P0 | `App.tsx` unmounts Home on navigation; `HomePage.tsx` owns job state and its listener. A running job can lose its visible status. | Own inspection/job state above the routes; match request/job IDs and show one persistent activity tray. Add a navigation-during-download regression test. |
| P0 | `inspection.py` video selectors include a generic `/best` fallback. This can select a different quality when the requested combination is unavailable. | Preserve the selected resolution or return a safe unavailable-format error. Rank audio independently and verify the final output. |
| P0 | Provider extraction broadly maps exceptions to `provider_unavailable`; Home also maps invocation failures to an engine error. | Distinguish safe network, engine, unavailable-media, and format failures. Offer Retry/New link without logging raw provider responses or URLs. |
| P1 | `FilesPage.tsx` fetches only on mount, ignores `library_changed`, and hides list failures as an empty library. Search misses get the first-download message. | Refresh on library changes and separate no downloads, no matches, loading, and load-failed states. Provide Clear filters or Retry as appropriate. |
| P1 | `commands.rs` returns artwork as a `data:` URL, but the configured CSP does not allow `data:` in `img-src`. | Verify artwork in the packaged webview and align a narrowly scoped local image transport with CSP. This is a static mismatch, not a reproduced runtime failure in this review. |
| P1 | Home uses substantial fixed vertical spacing; more quality rows compete with a 640 px minimum height. | Use the compact active-state layout and scrollable options area described above. Test keyboard access at all three approved sizes. |
| P1 | Transfers have separate video/audio and post-processing stages; a single stream's percentage is not an overall job percentage. | Show truthful stages: downloading, merging/converting, saving. Use bytes or an indeterminate state when totals are unknown. Acknowledge cancellation after cleanup. |

Also guard download submission while awaiting acknowledgement and handle rejected
open/cancel/download commands visibly. Do not add queueing, resume, deletion, or
full media players simply to fill empty space in this milestone.

## Network diagnosis needs correction

The earlier context attributed socket error 10013 to Windows Firewall or endpoint
security and recommended changing those settings. The recorded checks ran in an
agent environment with restricted network permissions. Those results alone do
not establish the cause in the installed application. First reproduce through
the installed app or an approved diagnostic outside that restriction, then
classify the failure. No firewall change or network workaround was performed
in this review.

## Size and release discipline

The existing release files were measured again, without rebuilding:

| Runtime component | Bytes | Decimal MB |
| --- | ---: | ---: |
| Windows host | 11,527,680 | 11.53 |
| Python engine | 22,425,873 | 22.43 |
| FFmpeg | 102,856,192 | 102.86 |
| Total of these three components | 136,809,745 | 136.81 |

That is approximately 130.47 MiB, not 130.47 MB. The three-file subtotal leaves
13.19 MB under the user's 150 MB limit, before any additional installation files
or prerequisites. Use 140 MB decimal as the conservative internal payload target;
some existing documentation says 140 MiB instead. Measure the complete installed
payload before claiming that release gate passes. FFmpeg dominates this subtotal;
the UI refinements do not require a larger framework or extra motion library.
These mockup PNGs belong only in design documentation, not the application bundle.

## Suggested next iteration

1. Verify the installed app's real inspection/download failure with authorized
   network access; test exact selected output quality and safe errors.
2. Implement shared session state, navigation-safe progress, and Files refresh
   with failing tests first.
3. Apply the Home and format-panel refinement, then the Files layout and its
   distinct empty/error states. Preserve the existing security boundaries.
4. Validate 1366×768, 1024×640, and 960×640, keyboard/focus/reduced-motion states,
   packaged artwork, cancellation, MP4/MP3 output, and the complete size budget.
5. Only after this flow is reliable, start the Video player milestone.

Repository documentation also needs a separate consistency pass: root context
describes scaffolding as pending while app context records release artifacts;
older plans have review-status and bot references that no longer reflect the
current tree. Preserve the ongoing repository cleanup rather than overwriting it.

## Changes and verification in this review

Added three PNGs, a local static gallery, and this review; updated application
context. No production source, dependencies, or build configuration changed.
Checked generated image signatures/dimensions, local gallery references, and
whitespace. Existing app test/build results are historical and were not rerun.
