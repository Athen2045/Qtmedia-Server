# Qtmedia CLI Context Snapshot

**Verified:** 2026-09-27
**Current phase:** Standalone CLI maintenance and desktop sidecar integration.

## Completed

- The CLI is isolated under `Qtmedia/` with its own package, tests,
  benchmarks, documentation, and runtime data.
- The CLI package owns terminal search, source adapters, direct downloads,
  cancellation, and the local search cache.
- The desktop-facing service boundary is being developed under
  `src/qtmedia/desktop_service/` with focused tests.
- Retired messaging-bot code and deployment references were removed from the
  workspace; the CLI does not depend on them.
- Rechecked the SpankBang downloader path against the current yt-dlp package.
  The venv has yt-dlp 2026.08.19, yt-dlp-ejs 0.8.0, and curl-cffi 0.15.0;
  the SpankBang options resolve to the upstream-recommended `chrome`
  impersonation target.
- Added local `.env` loading to the launcher and configured Firefox
  profile cookies with the installed Firefox 156.0.1 user-agent for SpankBang
  challenge requests. The profile is configured by its actual directory path
  because yt-dlp could not resolve Firefox's friendly profile name. The `.env`
  file is ignored and contains no copied cookies.

## Next concrete action

Continue the QtmediaApp sidecar work. If SpankBang still returns 403 outside
the app's current network path, configure same-browser cookies and a matching
user agent; the upstream site issue remains open.

## Open decisions or blockers

- Keep CLI commands and terminal behavior backward compatible.
- The complete packaged desktop sidecar build remains to be verified.

## Relevant files

- `Qtmedia/src/qtmedia/`
- `Qtmedia/tests/`
- `Qtmedia/benchmarks/`
- `Qtmedia/src/qtmedia/desktop_service/`
- `Qtmedia/tests/test_desktop_service.py`
- `QtmediaApp/`

## Verification

The SpankBang verification pass is complete. `pytest -q tests/test_search.py
tests/test_downloader.py` passed (45 tests), Ruff passed, compileall passed,
and `git diff --check` reported no whitespace errors. No package update was
available from the configured package index.
