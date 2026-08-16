# Project Structure and Dead-File Cleanup Design

## Goal

Reduce root-level clutter and group implementation modules by responsibility without deleting user data or supported package commands.

## Structure

```text
src/private_search/
  app/       terminal CLI and menu
  search/    retrieval engine and ranking
  download/  download engine, cancellation, transfer policy
  sources/   site-specific adapters
  net/       HTTP client
  config.py
```

`main.py` and `main.bat` remain the only root interactive launchers. Package console commands continue to point at the new `app.cli` module. `python -m private_search` opens the same interactive menu.

## Cleanup

Remove the obsolete root compatibility launchers `search.py`, `download.py`, and `download.bat`. Keep downloaded media, `.claude` settings, caches, and the existing package console commands.

## Verification

Update all imports, tests, documentation, and compile commands. Run the complete pytest suite, Ruff, compileall, and a live `main.bat` smoke test.
