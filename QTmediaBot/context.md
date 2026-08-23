# QTmediaBot Context Snapshot

## Documentation and ignore-layout update — 2026-08-23

Added `QTmediaBot/docs/README.md` as the bot documentation index and added a
project-local `.dockerignore` that excludes runtime data, tests, caches,
environments, secrets, and deployment documentation from the bot image
context. Documentation remains tracked by Git.

## Cleanup verification — 2026-08-23

**Current phase:** Dead-code and runtime-storage cleanup.

**Completed:** Removed the copied CLI search package, CLI runtime config,
legacy bot downloader engine/control layer, and unused search-only provider
adapters. The bot now keeps only the direct-link transfer, HTTP, provider,
inspection, delivery, state, and Telegram application paths it imports. Native
runtime storage is limited to `var/telegram_jobs/` and
`var/telegram_state/`; the wrong-purpose cache/download directories were
removed. Defaults now resolve to the bot project root while explicit
environment paths remain unchanged.

**Next concrete action:** Run bot tests, lint, compile, Compose syntax, import
isolation, and runtime-layout checks.

**Open decisions or blockers:** Live Telegram acceptance remains an operator
task documented in the master setup specification.

**Changed files:** `QTmediaBot/src/qtmedia_bot/__init__.py`,
`bot/config.py`, `bot/services/{downloads,inspection,yt_options}.py`,
`pyproject.toml`, active documentation, and `QTmediaBot/var/`.

**Verification status:** `144 passed, 1 skipped`; Ruff, compileall, package
import/default-path, runtime layout, Compose config validation, and
`git diff --check` passed.

**Verified:** 2026-08-23  
**Current phase:** Workspace reorganization — bot split and verification
complete.  
**Application root:** `QTmediaBot/`  
**Python package:** `QTmediaBot/src/qtmedia_bot/`

## Completed

- Moved Telegram deployment files and bot tests into `QTmediaBot/`.
- Copied the required transfer, network, and provider-support modules into the
  bot package; search and search-cache code remains CLI-only.
- Renamed bot imports and the entry point to `qtmedia_bot` and `qtmedia-bot`.
- Updated Docker, Compose, CI, environment examples, tests, and workspace
  references to the new bot root.

## Next action

Continue bot work from this folder and use the master setup specification for
live acceptance tasks.

## Open decisions or blockers

- Live Telegram acceptance remains an operator task documented in the master
  setup specification and benchmark runbook.

## Relevant files

- `pyproject.toml`
- `src/qtmedia_bot/`
- `tests/bot/`
- `tests/deploy/`
- `deploy/telegram/`

## Verification

- `144 passed, 1 skipped` from `QTmediaBot/`.
- `ruff check .` passed from `QTmediaBot/`.
- `python -m compileall -q src tests` passed.
- `docker-compose --env-file .env -f deploy/telegram/compose.yaml config --quiet`
  passed. The installed `docker compose` wrapper could not access the Docker
  engine, so no live container operation was attempted.
