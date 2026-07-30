# Typer + Rich CLI (`qt`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two REPL-style console scripts (`private-search`, `private-download`) with a single Typer-based CLI, `qt`, that has `qt search` and `qt download` subcommands with Rich table/progress-bar output, while keeping `private-search`/`private-download` installed as aliases into the same commands.

**Architecture:** A new `src/private_search/cli.py` module owns a `typer.Typer` app with two commands. `search.py` and `downloader.py` keep their existing search/inspection/download logic untouched (`search()`, `deduplicate()`, `inspect_direct_url()`, `download_video()`) except `download_video()` gains one optional parameter. The REPL menu loop in `search.py` (`run()`, `print_menu()`, `download_selected()`, `filter_menu()`, `exclude_menu()`, `print_results()`, the ANSI color constants) is deleted once `cli.py` replaces everything it did.

**Tech Stack:** Typer (CLI parsing/help), Rich (tables, progress bars, prompts) — both new dependencies on top of the existing `requests`, `beautifulsoup4`, `yt-dlp` stack.

## Global Constraints

- `requires-python = ">=3.11"` (from `pyproject.toml`) — no syntax newer than 3.11 features.
- Add `typer>=0.12` and `rich>=13.7` to `[project.dependencies]` in `pyproject.toml`.
- No change to `search()`, `deduplicate()`, `inspect_candidate()`, `inspect_direct_url()`, site adapters, or the SQLite inspection cache.
- No change to `download_video()`'s existing behavior when called without the new `progress` parameter (default `None`).
- `qt` is the sole new console-script; `private-search`/`private-download` remain installed but forward into the same Typer commands (no duplicated logic).
- Root launcher scripts `search.py` and `download.py` (repo root) and `src/private_search/__main__.py` must keep working unmodified — they only ever call `search.main()` / `downloader.main()`.

---

### Task 1: `download_video()` accepts an optional progress callback

**Files:**
- Modify: `src/private_search/downloader.py:69-120` (the `download_video` function)
- Test: `tests/test_downloader.py`

**Interfaces:**
- Consumes: nothing new (existing `build_ydl_options`, `DownloadCancellation`).
- Produces: `download_video(video_url: str, progress: Callable[[dict], None] | None = None) -> None`. When `progress` is given, it is added to yt-dlp's `progress_hooks` alongside the existing cancellation hook, and `options["quiet"]`/`options["no_warnings"]` are set to `True` so yt-dlp's own console progress bar doesn't fight with the caller's custom one. When `progress` is `None` (the default), behavior is byte-for-byte identical to today.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_downloader.py`:

```python
import sys
import types

from private_search import downloader as downloader_module
from private_search.downloader import download_video, is_direct_video_url


class _FakeYDL:
    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def download(self, urls):
        for hook in self.options.get("progress_hooks", []):
            hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
        return 0


class _FakeDownloadError(Exception):
    pass


def _install_fake_yt_dlp(monkeypatch):
    fake_module = types.SimpleNamespace(
        YoutubeDL=_FakeYDL,
        utils=types.SimpleNamespace(DownloadError=_FakeDownloadError),
    )
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_module)
    return fake_module


def test_download_video_wires_custom_progress_hook_alongside_cancellation(monkeypatch):
    monkeypatch.setattr(downloader_module.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    _install_fake_yt_dlp(monkeypatch)

    received = []
    download_video("https://www.xvideos.com/video123/title", progress=received.append)

    assert received == [{"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100}]


def test_download_video_sets_quiet_only_when_progress_given(monkeypatch):
    monkeypatch.setattr(downloader_module.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    _install_fake_yt_dlp(monkeypatch)

    captured = {}
    original_ydl_init = _FakeYDL.__init__

    def capturing_init(self, options):
        captured.update(options)
        original_ydl_init(self, options)

    monkeypatch.setattr(_FakeYDL, "__init__", capturing_init)

    download_video("https://www.xvideos.com/video123/title")
    assert "quiet" not in captured
    assert len(captured["progress_hooks"]) == 1

    captured.clear()
    download_video("https://www.xvideos.com/video123/title", progress=lambda status: None)
    assert captured["quiet"] is True
    assert len(captured["progress_hooks"]) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_downloader.py -v`
Expected: `FAIL` — `download_video() got an unexpected keyword argument 'progress'`.

- [ ] **Step 3: Implement `progress` support**

In `src/private_search/downloader.py`, change the `download_video` signature and hook wiring:

```python
def download_video(video_url, progress=None):
    if not is_direct_video_url(video_url):
        print(f"Skipping non-video URL: {video_url}")
        return
    download_url = video_url
    output_title = None
    output_id = None
    if is_pmvhaven_url(video_url):
        try:
            metadata = fetch_metadata(video_url)
            print(f"PMVHaven title: {metadata.title}")
            if not metadata.media_url:
                print("PMVHaven API did not provide a downloadable media URL.")
                return
            download_url = metadata.media_url
            print(f"PMVHaven media source: {download_url}")
            output_title = re.sub(r"[\\/:*?\"<>|]+", "_", metadata.title).strip() or "video"
            output_id = metadata.video_id
        except (requests.RequestException, TypeError, ValueError) as error:
            print(f"PMVHaven API validation failed: {error}")
            return

    if shutil.which("ffmpeg") is None:
        print("ffmpeg is required to merge and repair MP4 streams.")
        print("Install it with: brew install ffmpeg")
        return

    print(f"Downloading: {video_url}")
    import yt_dlp

    try:
        options = build_ydl_options(video_url)
        if output_title and output_id:
            options["outtmpl"] = os.path.join(
                OUTPUT_FOLDER, f"{output_title} [{output_id}].%(ext)s"
            )
        cancellation = DownloadCancellation()
        options["progress_hooks"] = [cancellation.progress_hook]
        if progress is not None:
            options["progress_hooks"].append(progress)
            options["quiet"] = True
            options["no_warnings"] = True
        cancellation.start()
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                error_code = ydl.download([download_url])
        finally:
            cancellation.stop()
        if error_code:
            print(f"Download failed for {video_url} (exit code {error_code})")
        else:
            print(f"Download complete: {OUTPUT_FOLDER}")
    except DownloadCancelled:
        print("Download cancelled by user.")
    except yt_dlp.utils.DownloadError as error:
        print(f"Error downloading {video_url}: {error}")
```

(Only the signature line and the `options["progress_hooks"]` block change; everything else in the function is unchanged.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_downloader.py -v`
Expected: `PASS` (all tests, including the pre-existing `is_direct_video_url` ones).

- [ ] **Step 5: Commit**

```bash
git add src/private_search/downloader.py tests/test_downloader.py
git commit -m "feat: add optional progress callback to download_video"
```

---

### Task 2: `cli.py` skeleton with the `download` command

**Files:**
- Create: `src/private_search/cli.py`
- Modify: `pyproject.toml` (add `typer`/`rich` dependencies)
- Test: `tests/test_cli.py` (new)

**Interfaces:**
- Consumes: `downloader.download_video(video_url, progress=None)` from Task 1.
- Produces: `app = typer.Typer(name="qt")`, `console = rich.console.Console()`, a registered `download` command, a private `_run_download(url: str) -> None` helper that Task 3 will reuse, and `run_search_alias()`/`run_download_alias()` functions (the latter usable immediately; the former becomes callable once Task 3 registers the `search` command).

- [ ] **Step 1: Add dependencies**

In `pyproject.toml`, change:

```toml
dependencies = [
  "beautifulsoup4>=4.12",
  "requests>=2.31",
  "yt-dlp>=2025.1.0",
]
```

to:

```toml
dependencies = [
  "beautifulsoup4>=4.12",
  "requests>=2.31",
  "rich>=13.7",
  "typer>=0.12",
  "yt-dlp>=2025.1.0",
]
```

Then install:

```bash
python -m pip install -e ".[dev]"
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_cli.py`:

```python
from typer.testing import CliRunner

from private_search import cli

runner = CliRunner()


def test_download_command_invokes_download_video_with_progress_callback(monkeypatch):
    calls = []

    def fake_download_video(url, progress=None):
        calls.append(url)
        assert callable(progress)
        progress({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 4})
        progress({"status": "finished"})

    monkeypatch.setattr(cli.downloader, "download_video", fake_download_video)

    result = runner.invoke(cli.app, ["download", "https://example.test/video"])

    assert result.exit_code == 0
    assert calls == ["https://example.test/video"]
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: `FAIL` — `ModuleNotFoundError: No module named 'private_search.cli'`.

- [ ] **Step 4: Implement `cli.py`**

Create `src/private_search/cli.py`:

```python
"""Typer + Rich CLI: ``qt search`` and ``qt download``."""

from __future__ import annotations

import sys

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from typer.main import get_command

from . import downloader

app = typer.Typer(name="qt", help="Search and download videos from configured sites.")
console = Console()


def _run_download(url: str) -> None:
    progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    )
    with progress:
        task_id = progress.add_task("Downloading", total=None)

        def hook(status: dict) -> None:
            if status.get("status") == "downloading":
                total = status.get("total_bytes") or status.get("total_bytes_estimate")
                downloaded = status.get("downloaded_bytes", 0)
                progress.update(task_id, total=total, completed=downloaded)
            elif status.get("status") == "finished":
                task = progress.tasks[0]
                progress.update(task_id, completed=task.total or task.completed)

        downloader.download_video(url, progress=hook)


@app.command("download")
def download_cmd(
    url: str = typer.Argument(..., help="Direct video URL to download."),
) -> None:
    """Download a direct video URL with yt-dlp."""
    _run_download(url)


_click_app = get_command(app)


def run_search_alias() -> None:
    _click_app.main(args=["search", *sys.argv[1:]], prog_name="qt")


def run_download_alias() -> None:
    _click_app.main(args=["download", *sys.argv[1:]], prog_name="qt")
```

(`run_search_alias` is wired up in Task 4, once the `search` command exists — it is defined now because `run_download_alias` needs `_click_app` and both aliases naturally live together.)

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: `PASS`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/private_search/cli.py tests/test_cli.py
git commit -m "feat: add qt CLI with download command"
```

---

### Task 3: `search` command with Rich table + download prompt

**Files:**
- Modify: `src/private_search/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `search.search(query, filters, excludes, min_views) -> list[VideoResult]`, `search.inspect_direct_url(url) -> VideoResult | None`, `search.DEFAULT_EXCLUDES`, `search.MIN_VIEWS`, `VideoResult.title/url/site/view_count/max_height` (all existing, unchanged), and `_run_download(url: str)` from Task 2.
- Produces: a registered `search` command; `list[VideoResult]` results rendered as a `rich.table.Table`; a `rich.prompt.Prompt`-driven download selection.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
from private_search.search import VideoResult


def _make_result(title="Sample Title", url="https://example.test/1", views=42, height=1080):
    return VideoResult(
        title=title, url=url, site="ExampleSite", view_count=views, max_height=height, max_tbr=0.0
    )


def test_search_command_renders_table_and_downloads_chosen_result(monkeypatch):
    results = [_make_result(title="First"), _make_result(title="Second", url="https://example.test/2")]

    def fake_search(query, filters, excludes, min_views):
        assert query == "some title"
        assert filters == ["hd"]
        assert excludes == ["vr"]
        assert min_views == 10
        return results

    downloaded = []
    monkeypatch.setattr(cli.search, "search", fake_search)
    monkeypatch.setattr(cli, "_run_download", downloaded.append)

    result = runner.invoke(
        cli.app,
        ["search", "some title", "--filter", "hd", "--exclude", "vr", "--min-views", "10"],
        input="2\n",
    )

    assert result.exit_code == 0
    assert "First" in result.stdout
    assert "Second" in result.stdout
    assert downloaded == ["https://example.test/2"]


def test_search_command_blank_answer_skips_download(monkeypatch):
    monkeypatch.setattr(cli.search, "search", lambda *a, **k: [_make_result()])
    downloaded = []
    monkeypatch.setattr(cli, "_run_download", downloaded.append)

    result = runner.invoke(cli.app, ["search", "some title"], input="\n")

    assert result.exit_code == 0
    assert downloaded == []


def test_search_command_invalid_number_does_not_crash(monkeypatch):
    monkeypatch.setattr(cli.search, "search", lambda *a, **k: [_make_result()])
    downloaded = []
    monkeypatch.setattr(cli, "_run_download", downloaded.append)

    result = runner.invoke(cli.app, ["search", "some title"], input="99\n")

    assert result.exit_code == 0
    assert downloaded == []


def test_search_command_direct_url_inspects_instead_of_searching(monkeypatch):
    inspected = _make_result(title="Direct hit")
    calls = []

    def fake_inspect(url):
        calls.append(url)
        return inspected

    def fake_search(*args, **kwargs):
        raise AssertionError("search.search should not be called in --direct-url mode")

    monkeypatch.setattr(cli.search, "inspect_direct_url", fake_inspect)
    monkeypatch.setattr(cli.search, "search", fake_search)
    downloaded = []
    monkeypatch.setattr(cli, "_run_download", downloaded.append)

    result = runner.invoke(
        cli.app,
        ["search", "unused", "--direct-url", "https://example.test/direct"],
        input="1\n",
    )

    assert result.exit_code == 0
    assert calls == ["https://example.test/direct"]
    assert "Direct hit" in result.stdout
    assert downloaded == [inspected.url]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_cli.py -v`
Expected: `FAIL` — `No such command 'search'.`

- [ ] **Step 3: Implement the `search` command**

Add to `src/private_search/cli.py` (new imports at the top, alongside the existing ones):

```python
from typing import Optional

from rich.prompt import Prompt
from rich.table import Table

from . import search
```

Add below `_run_download` (and keep `download_cmd`/`_click_app`/alias functions after this block — reorder so `_click_app = get_command(app)` and the two `run_*_alias` functions are the last things in the file, after both commands are registered):

```python
def _render_results(results: list[search.VideoResult]) -> None:
    if not results:
        console.print("No matching videos found.")
        return
    table = Table(title=f"Search results ({len(results)} unique)")
    table.add_column("#", justify="right")
    table.add_column("Title")
    table.add_column("Site")
    table.add_column("Views", justify="right")
    table.add_column("Best quality")
    for index, result in enumerate(results, 1):
        views = "unknown" if result.view_count is None else f"{result.view_count:,}"
        quality = f"{result.max_height}p" if result.max_height else "unknown quality"
        table.add_row(str(index), result.title, result.site, views, quality)
    console.print(table)


def _prompt_and_download(results: list[search.VideoResult]) -> None:
    if not results:
        return
    choice = Prompt.ask(
        f"Download which result? [1-{len(results)}] (blank to skip)", default=""
    ).strip()
    if not choice:
        return
    try:
        chosen = results[int(choice) - 1]
    except (ValueError, IndexError):
        console.print("[red]Invalid result number.[/red]")
        return
    _run_download(chosen.url)


@app.command("search")
def search_cmd(
    query: str = typer.Argument(..., help="Title or keywords to search for."),
    filter_: list[str] = typer.Option(
        [], "--filter", "-f", help="Only include results whose title/URL contains this term."
    ),
    exclude: list[str] = typer.Option(
        list(search.DEFAULT_EXCLUDES),
        "--exclude",
        "-e",
        help="Exclude results whose title/URL contains this term.",
    ),
    min_views: int = typer.Option(
        search.MIN_VIEWS, "--min-views", help="Minimum view count to include."
    ),
    direct_url: Optional[str] = typer.Option(
        None, "--direct-url", help="Inspect a single direct video URL instead of searching."
    ),
) -> None:
    """Search configured sites for a title, or inspect one direct URL."""
    if direct_url:
        result = search.inspect_direct_url(direct_url)
        results = [result] if result else []
    else:
        results = search.search(query, list(filter_), list(exclude), min_views)
    _render_results(results)
    _prompt_and_download(results)
```

Move the `_click_app = get_command(app)` line and the two `run_*_alias` functions (from Task 2) to the end of the file, after this new code, so both commands are registered on `app` before `get_command(app)` is called.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: `PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/private_search/cli.py tests/test_cli.py
git commit -m "feat: add qt search command with rich table and download prompt"
```

---

### Task 4: Remove the old REPL, wire aliases and `pyproject.toml`

**Files:**
- Modify: `src/private_search/search.py` (delete REPL-only code, replace `main()`)
- Modify: `src/private_search/downloader.py` (replace `main()`)
- Modify: `pyproject.toml` (`[project.scripts]`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `cli.run_search_alias()`, `cli.run_download_alias()` from Tasks 2/3.
- Produces: `search.main()` and `downloader.main()` remain as the two functions the root launcher scripts and `__main__.py` already import, now forwarding to the CLI aliases.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
def test_run_search_alias_forwards_argv_to_search_command(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["private-search", "some title", "--min-views", "5"])
    calls = []

    def fake_search(query, filters, excludes, min_views):
        calls.append((query, filters, excludes, min_views))
        return []

    monkeypatch.setattr(cli.search, "search", fake_search)

    with pytest.raises(SystemExit) as exc_info:
        cli.run_search_alias()

    assert exc_info.value.code in (0, None)
    assert calls == [("some title", [], list(cli.search.DEFAULT_EXCLUDES), 5)]


def test_run_download_alias_forwards_argv_to_download_command(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["private-download", "https://example.test/video"])
    calls = []
    monkeypatch.setattr(cli.downloader, "download_video", lambda url, progress=None: calls.append(url))

    with pytest.raises(SystemExit) as exc_info:
        cli.run_download_alias()

    assert exc_info.value.code in (0, None)
    assert calls == ["https://example.test/video"]
```

Add `import sys` and `import pytest` to the top of `tests/test_cli.py` if not already present.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_cli.py -v`
Expected: `FAIL` — `SystemExit` not raised (or search/download not invoked), since the aliases currently just call the same in-process Typer app without going through `sys.exit`... actually re-run first to see current behavior; if it already passes, skip to Step 3 confirming no regressions instead.

- [ ] **Step 3: Delete the REPL-only code from `search.py`**

In `src/private_search/search.py`, delete these top-level definitions entirely (search by name — line numbers shift as you go):

- The ANSI color constants block: `RESET`, `BOLD`, `CYAN`, `GREEN`, `YELLOW`, `DIM`.
- `print_results()`
- `print_menu()`
- `download_selected()`
- `filter_menu()`
- `exclude_menu()`
- `run()`

Replace the existing `main()` function with:

```python
def main() -> None:
    signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        from .cli import run_search_alias

        run_search_alias()
    except (KeyboardInterrupt, EOFError):
        print("\nStopped by user.")
```

Keep the `signal` import at the top of the file (it's still used here). Remove now-unused imports if any linter flags them (check with `ruff check src/private_search/search.py` after this step).

- [ ] **Step 4: Replace `main()` in `downloader.py`**

In `src/private_search/downloader.py`, replace the existing `main()` function with:

```python
def main() -> None:
    try:
        from .cli import run_download_alias

        run_download_alias()
    except (KeyboardInterrupt, EOFError):
        print("\nStopped by user.")
```

- [ ] **Step 5: Update `pyproject.toml` script entries**

Change:

```toml
[project.scripts]
private-search = "private_search.search:main"
private-download = "private_search.downloader:main"
```

to:

```toml
[project.scripts]
qt = "private_search.cli:app"
private-search = "private_search.cli:run_search_alias"
private-download = "private_search.cli:run_download_alias"
```

Reinstall so the console scripts refresh:

```bash
python -m pip install -e ".[dev]"
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest -v`
Expected: `PASS` — full suite, including `test_cli.py`, `test_downloader.py`, `test_search.py`, `test_download_control.py`, `test_http_client.py`, `test_pmvhaven.py`, `test_lustpress.py`.

Also run a lint/compile check:

```bash
ruff check .
python -m compileall -q src tests search.py download.py
```

- [ ] **Step 7: Manually smoke-test the installed commands**

```bash
qt --help
qt search --help
qt download --help
```

Expected: Typer's auto-generated help text for each, no tracebacks.

- [ ] **Step 8: Commit**

```bash
git add src/private_search/search.py src/private_search/downloader.py pyproject.toml tests/test_cli.py
git commit -m "refactor: remove REPL menu, wire private-search/private-download as qt aliases"
```

---

### Task 5: Update README for the new CLI

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing (documentation only).
- Produces: accurate usage instructions for `qt search`, `qt download`, and the aliases.

- [ ] **Step 1: Replace the Usage section**

In `README.md`, replace:

```markdown
## Usage

Start the search interface:

\`\`\`bash
python search.py
\`\`\`

Start the direct-link downloader:

\`\`\`bash
python download.py
\`\`\`

The installed console commands are also available:

\`\`\`bash
private-search
private-download
\`\`\`

The search interface prompts for a title, applies the configured filters, and
shows matching preview links. The downloader prompts for a URL and saves the
result under `var/downloads/`. Enter `q` and press Return when prompted during a
download to request cancellation; press `Ctrl+C` to interrupt the application.
```

with:

```markdown
## Usage

After installing (`python -m pip install -e ".[dev]"`), the `qt` command is
available:

\`\`\`bash
qt search "video title" --filter hd --exclude vr --min-views 1000
qt download https://example.com/video-page
\`\`\`

`qt search` shows matching results in a table and then asks which result
number to download (leave blank to skip). Pass `--direct-url <url>` to
inspect a single URL with yt-dlp instead of searching. `qt download <url>`
downloads a direct video URL immediately, showing a live progress bar.

The root launcher scripts and the pre-existing console commands still work
and forward into the same commands:

\`\`\`bash
python search.py "video title"
python download.py https://example.com/video-page
private-search "video title"
private-download https://example.com/video-page
\`\`\`

Downloads are saved under `var/downloads/`. Enter `q` and press Return when
prompted during a download to request cancellation; press `Ctrl+C` to
interrupt the application.
```

- [ ] **Step 2: Verify the README renders sensibly**

Run: `python -m compileall -q src tests search.py download.py` (confirms nothing else broke) and read the updated section back to check the fenced code blocks are balanced.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update README for qt CLI usage"
```
