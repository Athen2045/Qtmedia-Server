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


_click_app = get_command(app)


def run_search_alias() -> None:
    _click_app.main(args=["search", *sys.argv[1:]], prog_name="qt")


def run_download_alias() -> None:
    _click_app.main(args=["download", *sys.argv[1:]], prog_name="qt")
