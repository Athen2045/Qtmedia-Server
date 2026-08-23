# Project Structure and Dead-File Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move implementation modules into concise domain folders and remove obsolete root launchers while preserving supported behavior.

**Architecture:** The package will use `app`, `search`, `download`, `sources`, and `net` modules. The existing public behavior stays behind the same function-level interfaces, so callers gain locality without a broad behavioral rewrite.

**Tech Stack:** Python 3.11+, setuptools package discovery, pytest, Ruff, Rich, Typer.

## Global Constraints

- Keep `main.py`, `main.bat`, `qt`, `qtmedia-search`, and `qtmedia-download` working.
- Delete only `search.py`, `download.py`, and `download.bat` as obsolete root launchers.
- Do not delete `var/`, downloaded media, `.claude/`, caches, or local settings.
- Preserve all tests and behavior unless an import path must change.

### Task 1: Move modules

- Create package folders `app`, `search`, `download`, `sources`, and `net` with `__init__.py` files.
- Move `cli.py` to `app/cli.py`.
- Move `search.py` and `search_quality.py` to `search/engine.py` and `search/quality.py`.
- Move `downloader.py`, `download_control.py`, and `transfer_options.py` to `download/engine.py`, `download/control.py`, and `download/transfer.py`.
- Move `lustpress.py` and `pmvhaven.py` to `sources/`.
- Move `http_client.py` to `net/`.

### Task 2: Update interfaces and references

- Update relative imports to the new package locations.
- Update `pyproject.toml`, `main.py`, and `__main__.py` entry points.
- Update all tests and documentation references.

### Task 3: Remove obsolete files and verify

- Delete root `search.py`, `download.py`, and `download.bat`.
- Run pytest, Ruff, compileall, and the `main.bat` smoke test.
- Confirm user-owned `var/` and `.claude/` remain untouched.
