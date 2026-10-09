# Qtmedia Instructions

## Scope

Qtmedia owns the terminal search and download workflow. Keep desktop-specific
UI and packaging code outside this folder.

## File placement

- CLI commands and presentation: `src/qtmedia/app/`
- Search and ranking: `src/qtmedia/search/`
- Download and cancellation: `src/qtmedia/download/`
- Source adapters: `src/qtmedia/sources/`
- HTTP behavior: `src/qtmedia/net/`
- Tests: `tests/`
- Benchmarks: `benchmarks/`
- Local runtime data: `var/downloads/` and `var/cache/` only

## Change rules

- Preserve the existing CLI commands and interactive menu behavior.
- Keep secrets, cookies, downloaded media, and cache databases out of Git.
- Make package changes in `qtmedia`, not in the desktop host or frontend.
- Update root documentation when a public path or command changes.

## Verification

From `Qtmedia/`, run:

```bash
ruff check .
pytest -q
python -m compileall -q src tests main.py benchmarks
```
