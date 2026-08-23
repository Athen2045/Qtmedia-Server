"""Typer + Rich CLI: ``qt search`` and ``qt download``."""

from __future__ import annotations

import sys
from typing import Annotated
from urllib.parse import urlparse

import typer
from rich.console import Console
from rich.panel import Panel
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

from ..download import engine as downloader
from ..search import engine as search
from ..search.preview import render_thumbnail

app = typer.Typer(name="qt", help="Search and download videos from configured sites.")
console = Console()
error_console = Console(stderr=True)


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

        completed = downloader.download_video(url, progress=hook)
        if completed is False:
            raise typer.Exit(code=1)


@app.command("download")
def download_cmd(
    url: Annotated[str, typer.Argument(help="Direct video URL to download.")],
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


def _render_selected_result(result: search.VideoResult) -> None:
    """Show the selected result's details and optional Kitty thumbnail."""
    views = "unknown" if result.view_count is None else f"{result.view_count:,}"
    quality = f"{result.max_height}p" if result.max_height else "unknown quality"
    details = "\n".join(
        (
            f"Site: {result.site}",
            f"Views: {views}",
            f"Best quality: {quality}",
            f"URL: {result.url}",
        )
    )
    console.print(Panel(details, title=result.title, expand=False))
    if not result.thumbnail_url:
        console.print("[dim]No thumbnail was provided for this result.[/dim]")
        return
    if render_thumbnail(result.thumbnail_url):
        console.print("[dim]Thumbnail preview shown above.[/dim]")
        return
    console.print(
        "[dim]Kitty thumbnail preview unavailable. "
        f"Open the thumbnail URL if needed: {result.thumbnail_url}[/dim]"
    )


def _prompt_and_download(results: list[search.VideoResult], *, interactive: bool = False) -> None:
    if not results:
        return
    while True:
        choice = Prompt.ask(
            f"Preview result [1-{len(results)}], or press Enter/q to skip", default=""
        ).strip()
        if not choice or choice.casefold() == "q":
            return
        try:
            number = int(choice)
            if not 1 <= number <= len(results):
                raise ValueError(number)
            chosen = results[number - 1]
        except ValueError:
            error_console.print(
                f"[red]Choose a number from 1 to {len(results)}, or press Enter/q to skip.[/red]"
            )
            if interactive:
                return
            raise typer.Exit(code=2)

        _render_selected_result(chosen)
        action = Prompt.ask(
            "Type y to download, r to choose another result, or press Enter to cancel",
            default="",
        ).strip().casefold()
        if action == "r":
            _render_results(results)
            continue
        if action in {"y", "yes"}:
            _run_download(chosen.url)
        return


def _pause_for_menu() -> None:
    Prompt.ask("Press Enter to return to the main menu", default="", show_default=False)


def _interactive_search() -> None:
    query = Prompt.ask("Search keywords").strip()
    if not query:
        error_console.print("[yellow]Enter at least one search term.[/yellow]")
        return
    results = search.search(query, [], list(search.DEFAULT_EXCLUDES), search.MIN_VIEWS)
    _render_results(results)
    _prompt_and_download(results, interactive=True)
    _pause_for_menu()


def _interactive_download() -> None:
    url = Prompt.ask("Video page URL").strip()
    if not url:
        return
    try:
        _run_download(url)
    except typer.Exit:
        pass
    _pause_for_menu()


def _interactive_inspect() -> None:
    url = Prompt.ask("Video page URL").strip()
    if not url:
        return
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        error_console.print("[red]Enter a complete http:// or https:// video URL.[/red]")
    else:
        result = search.inspect_direct_url(url)
        _render_results([result] if result else [])
    _pause_for_menu()


def _interactive_help() -> None:
    console.print("[bold]QT Downloader help[/bold]")
    console.print("1 searches configured sites and offers to download a result.")
    console.print("2 downloads a direct video page URL with progress.")
    console.print("3 inspects metadata only; it never downloads the video.")
    console.print("Use q at the menu to exit.")
    _pause_for_menu()


def interactive_menu() -> None:
    """Run the simple menu used by the root Windows launcher."""
    while True:
        console.rule("[bold]QT Downloader[/bold]")
        console.print("[bold]1[/bold] Search for a video")
        console.print("[bold]2[/bold] Download a video link")
        console.print("[bold]3[/bold] Inspect a video link")
        console.print("[bold]4[/bold] Help")
        console.print("[bold]q[/bold] Quit")
        choice = Prompt.ask("Choose an option").strip().casefold()
        if choice == "1":
            _interactive_search()
        elif choice == "2":
            _interactive_download()
        elif choice == "3":
            _interactive_inspect()
        elif choice == "4":
            _interactive_help()
        elif choice == "q":
            console.print("Goodbye.")
            return
        else:
            error_console.print("[yellow]Choose 1, 2, 3, 4, or q.[/yellow]")


@app.command("search")
def search_cmd(
    query: Annotated[
        str | None,
        typer.Argument(help="Title or keywords to search for; omit when using --direct-url."),
    ] = None,
    filter_: Annotated[
        list[str],
        typer.Option(
            "--filter", "-f", help="Only include results whose title/URL matches this word or phrase."
        ),
    ] = (),
    exclude: Annotated[
        list[str],
        typer.Option(
            "--exclude",
            "-e",
            help="Exclude results whose title/URL matches this word or phrase.",
        ),
    ] = tuple(search.DEFAULT_EXCLUDES),
    min_views: Annotated[
        int, typer.Option("--min-views", help="Minimum view count to include.")
    ] = search.MIN_VIEWS,
    direct_url: Annotated[
        str | None,
        typer.Option("--direct-url", help="Inspect a single direct video URL instead of searching."),
    ] = None,
    no_prompt: Annotated[
        bool,
        typer.Option("--no-prompt", help="Show results without asking whether to download one."),
    ] = False,
) -> None:
    """Search configured sites for a title, or inspect one direct URL."""
    if direct_url:
        parsed = urlparse(direct_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            error_console.print("[red]Enter a complete http:// or https:// video URL.[/red]")
            raise typer.Exit(code=2)
        result = search.inspect_direct_url(direct_url)
        results = [result] if result else []
        _render_results(results)
        return
    if not query:
        raise typer.BadParameter("provide a search query or use --direct-url URL")
    results = search.search(query, list(filter_), list(exclude), min_views)
    _render_results(results)
    if not no_prompt:
        _prompt_and_download(results)


_click_app = get_command(app)


def run_search_alias() -> None:
    _click_app.main(args=["search", *sys.argv[1:]], prog_name="qt")


def run_download_alias() -> None:
    _click_app.main(args=["download", *sys.argv[1:]], prog_name="qt")
