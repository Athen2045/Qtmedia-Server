# Qtmedia Context Snapshot

## Documentation and ignore-layout update — 2026-08-23

Added `Qtmedia/docs/README.md` as the CLI documentation index and added a
project-local `.dockerignore` that excludes runtime data, tests, caches,
environments, secrets, and generated package metadata from future image
contexts. Documentation remains tracked by Git.

## Cleanup verification — 2026-08-23

**Current phase:** Dead-code and runtime-storage cleanup.

**Completed:** Removed the obsolete bot-only runtime/search copies from the
CLI-facing workspace boundary and removed the misplaced Qtmedia Telegram
metadata directory plus the old virtual environment nested inside the CLI
cache. The CLI runtime now contains only `var/downloads/` and `var/cache/`.
Existing downloaded media and `var/cache/search.sqlite3` were preserved.

**Next concrete action:** Run the focused Qtmedia and QTmediaBot test, lint,
compile, import-isolation, and runtime-layout checks.

**Open decisions or blockers:** None currently.

**Changed files:** `Qtmedia/README.md`, `Qtmedia/instructions.md`,
`QTmediaBot/src/qtmedia_bot/`, the active architecture/setup documentation,
and runtime directories under `Qtmedia/var/` and `QTmediaBot/var/`.

**Verification status:** `92 passed`; Ruff, compileall, package import, runtime
layout, and `git diff --check` passed.

**Verified:** 2026-08-23  
**Current phase:** Workspace reorganization — CLI split and verification
complete.  
**Application root:** `Qtmedia/`  
**Python package:** `Qtmedia/src/qtmedia/`

## Completed

- Moved the CLI launcher, packaging metadata, tests, benchmarks, and CLI
  runtime directory into `Qtmedia/`.
- Renamed the runtime package from `private_search` to `qtmedia`.
- Removed the Telegram dependency and bot entry point from the CLI package.
- Updated CLI documentation, CI paths, environment examples, and console
  aliases.

## Next action

Continue CLI work from this folder without importing from `QTmediaBot`.

## Open decisions or blockers

- None for the folder split. CLI behavior should remain unchanged.

## Relevant files

- `pyproject.toml`
- `src/qtmedia/`
- `tests/`
- `main.py` and `main.bat`

## Verification

- `92 passed` from `Qtmedia/`.
- `ruff check .` passed from `Qtmedia/`.
- `python -m compileall -q src tests main.py benchmarks` passed.
