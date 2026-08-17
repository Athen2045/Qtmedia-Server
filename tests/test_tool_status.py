from __future__ import annotations

from contextlib import contextmanager

from private_search.ai.actions import AgentAction
from private_search.ai.tools import ToolRegistry
from private_search.progress import ProgressEvent
from private_search.search import engine as search_module


class Approved:
    def confirm(self, request):
        return True


def test_tool_registry_reports_running_status_around_external_action():
    messages: list[str] = []

    @contextmanager
    def status(message: str):
        messages.append(message)
        yield

    registry = ToolRegistry(
        Approved(),
        status=status,
        username_osint_tool=lambda action: [],
    )

    registry.dispatch(
        AgentAction(
            action="username_osint",
            reason="The user requested a username lookup.",
            username="alice",
        )
    )

    assert messages == ["Running a username search …"]


def test_tool_registry_forwards_progress_to_opt_in_adapter():
    events: list[ProgressEvent] = []

    @contextmanager
    def progress(message: str):
        assert message == "Running a username search …"
        yield events.append

    def adapter(action, *, progress):
        progress(ProgressEvent("scan", "Scanning sites", completed=1, total=2))
        return []

    registry = ToolRegistry(
        Approved(),
        progress=progress,
        username_osint_tool=adapter,
    )

    registry.dispatch(
        AgentAction(
            action="username_osint",
            reason="The user requested a username lookup.",
            username="alice",
        )
    )

    assert events == [ProgressEvent("scan", "Scanning sites", completed=1, total=2)]


def test_default_search_reports_staged_progress(monkeypatch):
    events: list[ProgressEvent] = []

    def fake_search(query, *, source_scope, progress):
        assert query == "needle"
        assert source_scope == "youtube"
        progress(ProgressEvent("query", "Querying sources", completed=1, total=3))
        progress(ProgressEvent("rank", "Ranking results", completed=2, total=3))
        return []

    @contextmanager
    def progress(_message: str):
        yield events.append

    monkeypatch.setattr(search_module, "search", fake_search)
    registry = ToolRegistry(Approved(), progress=progress)

    registry.dispatch(
        AgentAction(
            action="refine_search",
            reason="The user requested a search.",
            query="needle",
            search_scope="youtube",
        )
    )

    assert events == [
        ProgressEvent("prepare", "Preparing", completed=0, total=3),
        ProgressEvent("query", "Querying sources", completed=1, total=3),
        ProgressEvent("rank", "Ranking results", completed=2, total=3),
        ProgressEvent("complete", "Complete", completed=3, total=3),
    ]
