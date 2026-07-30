"""Typer + Rich CLI: ``qt search`` and ``qt download``."""

from __future__ import annotations

import sys
from typing import Optional

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
from rich.prompt import Prompt
from rich.table import Table
from typer.main import get_command

from . import downloader, search

app = typer.Typer(name="qt", help="Search and download videos from configured sites.")
console = Console()


@app.callback()
def main() -> None:
    """Search and download videos from configured sites."""
    # Present so Typer always dispatches subcommands (``search``/``download``)
    # instead of collapsing to single-command mode when only one is registered.


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


_click_app = get_command(app)


def run_search_alias() -> None:
    _click_app.main(args=["search", *sys.argv[1:]], prog_name="qt")


def run_download_alias() -> None:
    _click_app.main(args=["download", *sys.argv[1:]], prog_name="qt")
