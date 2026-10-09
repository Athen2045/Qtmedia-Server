# Approved mockups and download-location Settings

Status: approved by the user's 2026-09-14 request to build the improved workflow.
Date: 2026-09-14.

## Approved changes

- Implement the Home, format-selection, and Files direction from the three
  mockups in this directory, using the existing bundled font and supplied SVGs.
- Omit the entire Home storage strip ("Saved to your Qtmedia library" and its
  adjacent folder shortcut). Storage preferences belong in Settings; Files
  retains its Open folder action.
- Activate Settings in the existing five-destination rail. Video and Music
  remain coming-soon destinations; no player or new adapters in this change.
- Preserve real available-format choices, accessible downward reveal, responsive
  layout, and truthful download progress. Do not ship the fictional mockup data.

## Proposed Settings behavior

One Download location card shows the full effective library path with wrapping
or horizontal text scrolling, a Default/Custom label, and three controls:
Change folder, Open folder, and Use default. Use the same dark surfaces and
restrained accent as Files, not a separate visual style.

Default remains the current Rust-computed application-data path:
`<app-data>/Qtmedia/library/`. This preserves existing installations.

Change folder opens a native folder picker. The selected directory is a parent:
the app previews `<selected-folder>/Qtmedia/library/` and asks the user to apply
that exact destination. If an existing Qtmedia library is selected directly,
recognize it rather than nesting another Qtmedia/library inside it. No arbitrary
directory's temp folder may become a cleanup target.

The preference survives restarts and is stored locally in application data, not
inside the chosen media directory. Dialog cancellation leaves everything alone.
Use default follows the same validation and application process.

Recommended first version: switching libraries does not copy, move, or delete
existing downloads. New downloads and Files use the selected library. Explain
this before Apply, and allow the old library to be selected again. Do not merge
multiple roots into a single library index in this milestone.

Alternative approaches considered:

- Move existing files automatically: keeps one complete library but introduces
  potentially large transfers, disk-space checks, interruption recovery, and
  rollback. Defer until explicitly requested.
- Show every previous location together: convenient, but requires persistent
  multi-root identity, availability handling, and broader path authorization.
  Defer for this version.

## Storage boundaries and transitions

Rust owns the picker, preference, canonical root, path validation, and sidecar
lifecycle. React receives displayable location data and narrow actions only;
it gains no arbitrary filesystem or shell permission. Python remains on JSONL.

Validate that a destination is a writable local directory, reject filesystem
roots and unsafe/reparse escapes, and create only application-owned subfolders.
Never recursively clean a user-selected generic folder. Existing unmanaged
content must not be adopted as disposable temporary data.

Serialize root changes against inspection, download, cancellation cleanup, and
open/list operations. Disable Apply while work is active, and enforce the same
guard in Rust. After jobs finish, prepare and validate the new root, restart the
engine with it, and confirm readiness before reporting success. On failure keep
or restore the previous root/preference and show a safe error. Handle expected
old-engine shutdown separately from unexpected process failure.

Invalidate old inspection sessions and stale file rows on a successful switch;
refresh Files against the new root. Stale open requests must not resolve against
the new root by coincidence. Use a library generation/identity in the host
boundary. Shared job state above navigation keeps progress and busy guards
consistent on Home, Files, and Settings.

If a saved custom destination is unavailable at startup, keep Settings usable
and explain the issue. Do not silently download to a different destination;
offer reselecting a folder or explicitly using the default.

## Verification and handoff

Write failing tests before implementation for first-run default, saved custom
location, picker cancellation, invalid/unwritable directories, active-job guard,
failed engine switch rollback, unavailable startup destination, and unchanged
old files. Verify confined temp cleanup and stale-file request rejection.

React tests cover active Settings, visible path/actions, Apply state/errors,
navigation-safe progress, Files refresh and empty/error states, and the absence
of the Home storage strip. Rust/sidecar tests cover persistence and root handoff.

Visually check Home, formats, Files, and Settings at 1366×768, 1024×640, and
960×640 with keyboard focus and reduced motion. Run relevant existing suites,
frontend build, and Rust checks. A later installer rebuild must measure complete
payload size for information. The user removed the 140 MB internal target and
150 MB product ceiling on 2026-09-15.

This design is implemented by
`docs/superpowers/plans/2026-09-14-qtmedia-improved-workflow.md`. The first
version uses the no-migration single-library behavior described above.
