# Typer + Rich CLI (`qt`) Design

## Goal

Replace the ad hoc console-script setup with a single installable CLI, `qt`,
built on Typer (argument parsing, `--help`) and Rich (colored output, tables,
progress bars). Two subcommands: `qt search` and `qt download`.

## Background

Today the project installs two console scripts via `pyproject.toml`:

- `private-search` -> `private_search.search:main` — an interactive REPL with
  a numbered menu (search, set include filters, set excludes, inspect a
  direct URL, download a result by number, quit). Filters/excludes/min-views
  are session state set through menu prompts. Output is plain `print()` with
  hand-rolled ANSI color constants and an ASCII box-drawn dashboard.
- `private-download` -> `private_search.downloader:main` — a simpler REPL
  that repeatedly prompts for a direct video URL and downloads it, printing
  plain-text progress lines.

Neither uses a CLI argument-parsing library; both are line-oriented REPLs.
`rich` and `typer` are not yet a dependency.

## Non-goals

- No change to search/inspection logic itself (`search()`, `deduplicate()`,
  `inspect_candidate()`, site adapters, caching) beyond what's needed to
  reuse it from the new commands.
- No change to download logic itself (`download_video()`'s use of yt-dlp,
  PMVHaven metadata resolution, ffmpeg requirement, cancellation) beyond
  adding an optional progress callback.
- Not building a TUI — Typer + Rich give a scriptable, single-shot CLI, not
  a persistent interactive application.

## Architecture

A new Typer app lives in `src/private_search/cli.py`:

```
qt search "<title>" [--filter TEXT]... [--exclude TEXT]... [--min-views N] [--direct-url URL]
qt download <url>
```

`qt` becomes the sole console-script entry point in `pyproject.toml`:

```toml
[project.scripts]
qt = "private_search.cli:app"
private-search = "private_search.cli:run_search_alias"
private-download = "private_search.cli:run_download_alias"
```

`run_search_alias()`/`run_download_alias()` are thin functions that invoke
the same Typer `app` object with `["search"]` / `["download"]` prepended to
`sys.argv[1:]`, so `private-search --filter x "title"` behaves identically
to `qt search --filter x "title"`. There is exactly one implementation of
each command's behavior.

The existing REPL loop (`search.run()`, `search.print_menu()`, menu-driven
filters/excludes/min-views state, `search.download_selected()`) is removed.
Filters/excludes/min-views become one-shot CLI options instead of session
state set through a menu. `search.main()` and `downloader.main()` (the
`if __name__ == "__main__"` entry points used by the root-level `search.py`
/ `download.py` launcher scripts) are updated to call into the new `cli.app`
the same way the console-script aliases do, so the root launcher scripts
keep working with the new flag-based interface.

## Components

1. **`src/private_search/cli.py`** (new)
   - `app = typer.Typer(name="qt")`, a module-level `console = rich.console.Console()`.
   - `search` command: parses `query`, `--filter/-f` (multiple), `--exclude/-e`
     (multiple, defaults to `search.DEFAULT_EXCLUDES`), `--min-views`
     (defaults to `search.MIN_VIEWS`), `--direct-url` (optional; when given,
     calls `search.inspect_direct_url()` instead of `search.search()`).
     Calls `search.search(query, filters, excludes, min_views)` unchanged,
     renders the returned `list[VideoResult]` as a `rich.table.Table`
     (columns: `#`, Title, Site, Views, Best Quality), then — if there are
     results — prompts with `rich.prompt.IntPrompt.ask(..., default=None)`
     for which result number to download (blank/`q` skips). On a valid
     choice, calls the shared download helper (below) with that result's URL.
   - `download` command: takes a required `url` argument, calls the shared
     download helper.
   - Shared helper `_run_download(url: str)`: builds a `rich.progress.Progress`
     with columns for percent, transfer speed, and ETA; defines a hook
     function that reads yt-dlp's progress-hook dict (`status`,
     `downloaded_bytes`/`total_bytes` or `_percent_str`, `speed`, `eta`) and
     updates the Progress task; calls
     `downloader.download_video(url, progress=hook)`.
   - `run_search_alias()` / `run_download_alias()`: call
     `app(["search", *sys.argv[1:]])` / `app(["download", *sys.argv[1:]])`.

2. **`src/private_search/search.py`**
   - Keep `search()`, `deduplicate()`, `inspect_direct_url()`,
     `relevance_score()`, adapters, and caching unchanged.
   - Remove `print_menu()`, `run()`, `download_selected()`, the ANSI color
     constants (`BOLD`/`GREEN`/`CYAN`/`YELLOW`/`DIM`/`RESET`), and
     `print_results()` (superseded by the Rich table in `cli.py`).
   - `main()` becomes `cli.run_search_alias()` (kept as a thin re-export for
     the root `search.py` launcher script and for anything importing
     `search.main`).

3. **`src/private_search/downloader.py`**
   - `download_video()` gains an optional `progress` parameter: a callable
     taking the same dict yt-dlp's progress hooks receive. Default value is
     a small function that reproduces today's `print()`-based lines, so
     existing callers/tests that don't pass `progress` see unchanged
     behavior. `cancellation.progress_hook` and the new `progress` callback
     are both registered in `options["progress_hooks"]` — cancellation stays
     a separate concern from progress display.
   - `main()` becomes `cli.run_download_alias()` (kept as a thin re-export
     for the root `download.py` launcher script).

4. **`pyproject.toml`**
   - Add `typer>=0.12` and `rich>=13.7` to `[project.dependencies]`.
   - Update `[project.scripts]` as shown above.

5. **Root launcher scripts (`search.py`, `download.py`)** — unchanged in
   shape (still `sys.path.insert` + import + call `main()`); the `main()`
   they import now comes from `cli.py`'s aliases instead of the REPL loop.

## Data flow

`qt search "title" --filter x --min-views 100`
  -> `search.search(query, filters, excludes, min_views)` (unchanged internals;
     still prints its own progress lines, e.g. "Inspected 5/12...")
  -> `list[VideoResult]`
  -> rendered as a Rich `Table`
  -> `IntPrompt` asks which `#` to download (blank/`q` skips)
  -> `_run_download(chosen_result.url)`
  -> `downloader.download_video(url, progress=rich_hook)`

`qt download <url>` -> `_run_download(url)` -> `downloader.download_video(url, progress=rich_hook)` directly, no search step.

`qt search --direct-url <url> "title"` -> `search.inspect_direct_url(url)` (title
positional still required by Typer but unused in this branch — documented in
`--help`) -> prints the inspected `VideoResult` via Rich, no download prompt.

## Error handling

No changes to error paths: bad/non-video URLs, missing `ffmpeg`,
`DownloadCancelled`, yt-dlp `DownloadError`, and search-worker exceptions
(`WORKER_EXCEPTIONS`) all still occur exactly where they do today. Messages
that used to be `print()` become `console.print()` with red/yellow styling
for errors/warnings; control flow is identical.

## Testing

- New `tests/test_cli.py` using `typer.testing.CliRunner` to invoke
  `qt search` and `qt download` with mocked `search.search()` /
  `downloader.download_video()`, asserting: correct arguments are forwarded,
  exit codes are 0 on success and non-zero on invalid input (e.g.
  non-integer response to the download prompt), and the alias entry points
  forward to the same commands.
- Existing `tests/test_search.py`, `tests/test_downloader.py`,
  `tests/test_download_control.py`, `tests/test_http_client.py`,
  `tests/test_pmvhaven.py`, `tests/test_lustpress.py` continue to pass
  unchanged: the functions they test keep their existing signatures (plus
  one optional trailing parameter on `download_video()`).

## Rollout

Single change, no migration needed — no persisted state depends on the old
menu/session-state model (filters/excludes/min-views were never saved
between runs).
