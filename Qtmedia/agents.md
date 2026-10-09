# Qtmedia Agent Guide

This folder contains only the Qtmedia command-line application. Its source,
tests, runtime data, and packaging configuration are independent of the desktop
application.

Before editing:

1. Read `context.md` and `instructions.md`.
2. Inspect `git status --short` from the workspace root.
3. Read the relevant application documentation under `docs/` and workspace
   documentation under `../docs/`.
4. Keep CLI changes inside `Qtmedia/` unless a workspace reference must change.
5. Run the focused CLI tests, Ruff, and compile checks before completion.

Do not import from `QtmediaApp` or recreate a shared package. If equivalent
behavior is needed by the desktop app, use its documented sidecar boundary.
