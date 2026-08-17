"""Rich confirmation prompts for actions with side effects."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table


@dataclass(frozen=True)
class ConfirmationRequest:
    """The exact operation the user is being asked to approve."""

    action: str
    summary: str
    details: tuple[tuple[str, str], ...]


class ConfirmationService:
    """Render a Rich confirmation or delegate to an injected decision function."""

    def __init__(
        self,
        *,
        decide: Callable[[ConfirmationRequest], bool] | None = None,
        console: Console | None = None,
    ) -> None:
        self._decide = decide
        self._console = console or Console()

    def confirm(self, request: ConfirmationRequest) -> bool:
        if self._decide is not None:
            return bool(self._decide(request))

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        table.add_row("Action", request.action)
        for label, value in request.details:
            table.add_row(label, value)
        self._console.print(
            Panel(table, title="Confirmation required", border_style="yellow", expand=False)
        )
        return Confirm.ask("Proceed?", default=False, console=self._console)
