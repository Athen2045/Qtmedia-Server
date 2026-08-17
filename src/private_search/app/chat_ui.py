"""Rich terminal chat shell for the local AI orchestrator."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlparse

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from .. import config
from ..ai.actions import AgentAction
from ..ai.chat import ChatOrchestrator, ChatTurnResult
from ..ai.client import LlamaClient, LlamaClientError
from ..ai.confirmation import ConfirmationService
from ..ai.runtime import (
    LlamaServer,
    LlamaServerError,
    RuntimeConfigurationError,
    RuntimeSettings,
)
from ..ai.tools import ToolExecutionError, ToolRegistry, ToolUnavailableError
from ..images import discover_images
from ..osint import BlackbirdAdapter, FaceAssistedReverseImageAdapter
from ..osint.confidence import confidence_band, normalize_score
from ..progress import ProgressEvent
from ..search.preview import render_local_image


@dataclass(frozen=True)
class LocalCommand:
    name: str
    argument: str = ""


class RichOperationProgress:
    """Render one tool operation as a staged, live-updating progress bar."""

    _OPERATION_LABELS: ClassVar[dict[str, str]] = {
        "Running a username search …": "Username",
        "Running an email search …": "Email",
        "Running a reverse image search …": "Reverse image",
        "Running a search …": "Search",
    }
    _PHASE_STAGES: ClassVar[dict[str, int]] = {
        "prepare": 0,
        "connect": 1,
        "upload": 1,
        "detect": 1,
        "scan": 2,
        "match": 2,
        "query": 2,
        "rank": 3,
        "process": 3,
        "parse": 3,
        "reverse": 3,
        "complete": 4,
    }

    def __init__(self, console: Console, title: str) -> None:
        self._console = console
        self._title = title
        self._operation_label = self._OPERATION_LABELS.get(title)
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        )
        self._task_id = None

    def __enter__(self):
        self._progress.start()
        self._task_id = self._progress.add_task(self._title, total=1, completed=0)
        return self.emit

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._task_id is not None and exc_type is None:
            task = self._progress.tasks[self._task_id]
            self._progress.update(
                self._task_id,
                completed=task.total if task.total is not None else task.completed,
            )
        self._progress.stop()

    def emit(self, event: ProgressEvent) -> None:
        if self._task_id is None:
            return
        if event.total is not None:
            total = max(1, event.total)
            completed = max(0, min(event.completed or 0, total))
        else:
            total = 4
            completed = self._PHASE_STAGES.get(event.phase, 0)
        self._progress.update(
            self._task_id,
            total=total,
            completed=completed,
            description=(
                f"{self._operation_label}: {event.message}"
                if self._operation_label
                else event.message
            ),
        )


def _progress_factory(console: Console):
    def create(title: str) -> RichOperationProgress:
        return RichOperationProgress(console, title)

    return create


def _render_chat_message(
    speaker: str,
    message: str,
    console: Console,
    *,
    style: str,
) -> None:
    """Render one chat turn with the speaker beside a wrapping message."""
    row = Table.grid(padding=0)
    row.add_column(width=max(len(speaker) + 1, 7), no_wrap=True, vertical="top")
    row.add_column(ratio=1)
    row.add_row(Text(f"{speaker}:", style=style), Text(message))
    console.print(row)


def parse_local_command(text: str) -> LocalCommand | None:
    """Parse a local UI command, leaving natural-language text untouched."""

    value = text.strip()
    if not value.startswith("/"):
        return None
    name, _, argument = value[1:].partition(" ")
    name = name.casefold()
    aliases = {"q": "quit", "exit": "quit", "h": "help", "think": "thinking"}
    return LocalCommand(aliases.get(name, name), argument.strip())


def select_project_image(console: Console) -> str | None:
    """Select a supported image from the project's image folder."""

    candidates = discover_images(config.PROJECT_ROOT / "image")
    if not candidates:
        console.print("[yellow]No supported images found in the project image folder.[/yellow]")
        return None
    if len(candidates) == 1:
        selected = candidates[0]
        console.print(f"[green]Selected image: {selected.relative_path}[/green]")
        return str(selected.path.resolve())

    table = Table(title="Project images")
    table.add_column("#", justify="right")
    table.add_column("Path")
    for index, candidate in enumerate(candidates, 1):
        table.add_row(str(index), candidate.relative_path)
        render_local_image(candidate.path)
    console.print(table)

    while True:
        choice = Prompt.ask(
            f"Choose image [1-{len(candidates)}], or press Enter/q to cancel",
            default="",
        ).strip()
        if not choice or choice.casefold() in {"q", "quit"}:
            return None
        try:
            index = int(choice)
            if not 1 <= index <= len(candidates):
                raise ValueError
            selected = candidates[index - 1]
        except (ValueError, IndexError):
            console.print(
                f"[yellow]Choose a number from 1 to {len(candidates)}, or press Enter/q to cancel.[/yellow]"
            )
            continue
        console.print(f"[green]Selected image: {selected.relative_path}[/green]")
        return str(selected.path.resolve())


def execute_local_command(
    command: LocalCommand,
    console: Console,
    chat: ChatOrchestrator | None = None,
) -> bool:
    """Execute a local UI command and return whether the chat should continue."""

    if command.name == "quit":
        return False
    if command.name == "help":
        console.print(
            Panel(
                "/about         Show Theia, model, and safeguards\n"
                "/thinking on   Enable thinking for conversational answers\n"
                "/thinking off  Disable thinking for conversational answers\n"
                "/context       Show context used versus remaining\n"
                "/options       Show current runtime options\n"
                "/help          Show this help\n"
                "/quit          Exit the chatbot",
                title="Chat commands",
                expand=False,
            )
        )
        return True
    if command.name == "thinking":
        if chat is None:
            console.print("[yellow]Thinking control is unavailable before chat starts.[/yellow]")
            return True
        value = command.argument.casefold()
        if value in {"on", "enable", "enabled", "1", "true"}:
            chat.set_thinking(True)
        elif value in {"off", "disable", "disabled", "0", "false"}:
            chat.set_thinking(False)
        elif value:
            console.print("[yellow]Use /thinking on or /thinking off.[/yellow]")
            return True
        state = "on" if chat.thinking_enabled else "off"
        console.print(f"[cyan]Thinking mode:[/cyan] {state}")
        return True
    if command.name in {"context", "options"}:
        if chat is None:
            console.print("[yellow]Context information is unavailable before chat starts.[/yellow]")
            return True
        usage = chat.context_usage
        source = "llama.cpp" if usage.exact else "estimated"
        lines = [
            f"Thinking: {'on' if chat.thinking_enabled else 'off'}",
            f"Context used: {usage.used:,} / {usage.total:,} tokens",
            f"Remaining: {usage.remaining:,} tokens",
            f"Measurement: {source}",
        ]
        if command.name == "options":
            lines.extend(
                [
                    "",
                    "Change with /thinking on or /thinking off.",
                    "Context size requires an application restart to change.",
                ]
            )
        console.print(
            Panel(
                "\n".join(lines),
                title="Runtime options" if command.name == "options" else "Context",
                expand=False,
            )
        )
        return True
    if command.name in {"about", "safety"}:
        console.print(
            Panel(
                "Name: Theia\n"
                "Personality: sharp, cheeky, concise, security-analyst mindset\n"
                "Delivery: dry wit, optional cussing, no flirtation, no emojis, no filler\n"
                "Modes: casual conversation, coding, debugging, planning, analysis, and tools\n"
                f"Model: {_configured_model_name()}\n\n"
                "Application safeguards:\n"
                "• Tool requests use a strict validated action schema.\n"
                "• It cannot create shell commands or select executables.\n"
                "• Search, downloads, reverse-image, and username/email OSINT tools require confirmation.\n"
                "• Tool access is through fixed Python adapters only.\n"
                "• The model server is restricted to loopback.\n"
                "• Casual/code replies use a free-form response lane; tool requests remain validated.\n"
                "• Internal reasoning is not exposed as hidden chain-of-thought.\n"
                "• No flirtation, suggestive, romantic, or adult-coded content.\n"
                "• Hard floor: no minors, coercion, exploitation, or non-consensual activity.\n\n"
                "Model safety note: the publisher markets this derivative as uncensored\n"
                "and reports 0/465 refusals, but publishes no reproducible safety\n"
                "methodology. Treat model output as untrusted text; the safeguards\n"
                "above are enforced by the application.",
                title="About Theia",
                expand=False,
            )
        )
        return True
    console.print(f"[yellow]Unknown command: /{command.name}. Use /help.[/yellow]")
    return True


def _configured_model_name() -> str:
    model_value = os.environ.get("PRIVATE_SEARCH_LLM_MODEL", "").strip()
    if model_value:
        return Path(model_value).name
    configured_model = getattr(config, "LLAMA_MODEL", None)
    if configured_model is not None:
        return Path(str(configured_model)).name
    return "configured locally"


def _render_search_results(results: object, console: Console) -> None:
    if not isinstance(results, list):
        return
    if not results:
        console.print("[dim]No matching results.[/dim]")
        return
    table = Table(title=f"Search results ({len(results)})")
    table.add_column("#", justify="right")
    table.add_column("Title")
    table.add_column("Site")
    table.add_column("Views", justify="right")
    table.add_column("Quality")
    for index, result in enumerate(results, 1):
        views = getattr(result, "view_count", None)
        height = getattr(result, "max_height", None)
        table.add_row(
            str(index),
            str(getattr(result, "title", result)),
            str(getattr(result, "site", "unknown")),
            "unknown" if views is None else f"{views:,}",
            "unknown" if height is None else f"{height}p",
        )
    console.print(table)


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _format_blackbird_metadata(metadata: object) -> str:
    if not isinstance(metadata, list) or not metadata:
        return ""
    parts: list[str] = []
    for item in metadata:
        text = ""
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            label = _safe_text(item.get("label")).strip()
            value = _safe_text(item.get("value")).strip()
            if label and value:
                text = f"{label}: {value}"
            elif label:
                text = label
            elif value:
                text = value
        else:
            text = _safe_text(item).strip()
        if text:
            parts.append(text)
        if len(parts) >= 3:
            break
    if not parts:
        return f"{len(metadata)} metadata item(s)"
    return "; ".join(parts)


def _render_blackbird_results(results: object, console: Console, *, kind: str) -> None:
    if not isinstance(results, list):
        return
    if not results:
        console.print(f"[dim]No {kind} matches found.[/dim]")
        return
    table = Table(title=f"Blackbird {kind} results ({len(results)})")
    table.add_column("#", justify="right")
    table.add_column("Site")
    table.add_column("Status")
    table.add_column("Category")
    table.add_column("Details")
    table.add_column("URL")
    for index, result in enumerate(results, 1):
        if not isinstance(result, dict):
            table.add_row(str(index), "unknown", "unknown", "", "", str(result))
            continue
        url = _safe_text(result.get("url")).strip()
        site = _safe_text(result.get("site")).strip() or urlparse(url).netloc or "unknown"
        status = _safe_text(result.get("status")).strip() or "unknown"
        category = _safe_text(result.get("category")).strip()
        metadata = _format_blackbird_metadata(result.get("metadata"))
        table.add_row(str(index), site, status, category, metadata, url)
    console.print(table)


def _render_reverse_image_results(results: object, console: Console) -> None:
    if not isinstance(results, list):
        return
    face_detections = [
        result for result in results if isinstance(result, dict) and result.get("kind") == "face_detection"
    ]
    search_errors = [
        result for result in results if isinstance(result, dict) and result.get("kind") == "reverse_search_error"
    ]
    matches = [
        result
        for result in results
        if not isinstance(result, dict)
        or result.get("kind") not in {"face_detection", "reverse_search_error"}
    ]
    if face_detections:
        details = []
        for face in face_detections:
            confidence = normalize_score(face.get("confidence"), source="confidence")
            score = "n/a" if confidence is None else f"{confidence:.1f}% ({confidence_band(confidence)})"
            details.append(f"{face.get('name', 'Face')}: {score}")
        console.print("[cyan]InsightFace[/cyan] " + ", ".join(details))
    for error in search_errors:
        console.print(f"[yellow]SmartImage:[/yellow] {error.get('error', 'reverse search failed')}")
    if not matches:
        console.print("[dim]No reverse-image matches found.[/dim]")
        return
    table = Table(title=f"Reverse-image results ({len(matches)})")
    table.add_column("#", justify="right")
    table.add_column("Name")
    table.add_column("Site")
    table.add_column("Confidence")
    table.add_column("URL")
    for index, result in enumerate(matches, 1):
        if not isinstance(result, dict):
            table.add_row(str(index), str(result), "unknown", "unknown", "")
            continue
        confidence = normalize_score(result.get("confidence"), source="confidence")
        if confidence is None:
            confidence = normalize_score(result.get("similarity"), source="similarity")
        confidence_text = "n/a"
        if confidence is not None:
            confidence_text = f"{confidence:.1f}% ({confidence_band(confidence)})"
        table.add_row(
            str(index),
            str(result.get("name", "")),
            str(result.get("site", "")),
            confidence_text,
            str(result.get("url", "")),
        )
    console.print(table)


def _prompt_search_download(result: ChatTurnResult, chat: ChatOrchestrator, console: Console) -> None:
    if result.tool_result is None or not result.tool_result.ok:
        return
    results = result.tool_result.data
    if not isinstance(results, list) or not results:
        return
    while True:
        choice = Prompt.ask(
            f"Download result [1-{len(results)}], or press Enter to skip",
            default="",
        ).strip()
        if not choice or choice.casefold() in {"q", "quit"}:
            return
        try:
            number = int(choice)
            selected = results[number - 1]
        except (ValueError, IndexError):
            console.print(f"[yellow]Choose a number from 1 to {len(results)}, or press Enter to skip.[/yellow]")
            continue
        url = getattr(selected, "url", None)
        if not isinstance(url, str) or not url.strip():
            console.print("[red]That result does not have a downloadable URL.[/red]")
            return
        action = AgentAction(
            action="download_media",
            reason="The user selected a result from the displayed search results.",
            url=url,
        )
        try:
            download_result = chat.execute_action(action)
        except (ToolExecutionError, ToolUnavailableError) as error:
            console.print(Panel(str(error), title="Theia error:", border_style="red"))
        else:
            render_chat_result(
                ChatTurnResult(
                    user_text=f"download result {number}",
                    action=action,
                    tool_result=download_result,
                    assistant_text=download_result.message,
                ),
                console,
                chat=chat,
            )
        return


def render_chat_result(
    result: ChatTurnResult,
    console: Console,
    *,
    chat: ChatOrchestrator | None = None,
) -> None:
    if result.error:
        _render_chat_message("Theia", result.error, console, style="bold red")
        return
    if result.action is not None and result.action.action == "refine_search" and result.tool_result:
        _render_search_results(result.tool_result.data, console)
        if chat is not None:
            _prompt_search_download(result, chat, console)
    if result.action is not None and result.action.action == "username_osint" and result.tool_result:
        _render_blackbird_results(result.tool_result.data, console, kind="username")
    if result.action is not None and result.action.action == "email_osint" and result.tool_result:
        _render_blackbird_results(result.tool_result.data, console, kind="email")
    if result.action is not None and result.action.action == "reverse_image_search" and result.tool_result:
        _render_reverse_image_results(result.tool_result.data, console)
    if result.assistant_text:
        _render_chat_message("Theia", result.assistant_text, console, style="bold magenta")


def interactive_chat() -> None:
    """Start the local model and run the Rich chatbot until the user exits."""

    console = Console()
    console.rule("[bold]THEIA[/bold]")
    server: LlamaServer | None = None
    try:
        settings = RuntimeSettings.from_environment()
        server = LlamaServer(settings)
        with console.status("Starting local llama.cpp…"):
            server.start()
        client = LlamaClient(server.server_url)
        confirmation = ConfirmationService(console=console)
        chat = ChatOrchestrator(
            client,
            ToolRegistry(
                confirmation,
                reverse_image_tool=FaceAssistedReverseImageAdapter(),
                username_osint_tool=BlackbirdAdapter(),
                email_osint_tool=BlackbirdAdapter(),
                reverse_image_resolver=lambda: select_project_image(console),
                progress=_progress_factory(console),
            ),
            context_window=settings.context_size,
        )
        console.print("[green]Local model ready.[/green] Type /help for commands or /quit to exit.")
        while True:
            try:
                text = Prompt.ask("[bold cyan]You[/bold cyan]")
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            command = parse_local_command(text)
            if command is not None:
                if not execute_local_command(command, console, chat):
                    break
                continue
            render_chat_result(chat.handle(text), console, chat=chat)
    except (LlamaServerError, RuntimeConfigurationError, LlamaClientError) as error:
        console.print(Panel(str(error), title="AI runtime unavailable", border_style="red"))
    finally:
        if server is not None:
            server.stop()
