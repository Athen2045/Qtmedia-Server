from __future__ import annotations

from pathlib import Path

import pytest

from private_search.ai.actions import AgentAction
from private_search.ai.confirmation import ConfirmationRequest
from private_search.ai.tools import ToolRegistry, ToolUnavailableError
from private_search.search import engine as search_module


class RecordingConfirmation:
    def __init__(self, approved: bool):
        self.approved = approved
        self.requests: list[ConfirmationRequest] = []

    def confirm(self, request: ConfirmationRequest) -> bool:
        self.requests.append(request)
        return self.approved


def search_action() -> AgentAction:
    return AgentAction(
        action="refine_search",
        reason="The user requested a search.",
        query="Bimbo PMV",
    )


def test_confirmed_search_calls_only_the_search_adapter():
    confirmation = RecordingConfirmation(approved=True)
    calls = []
    registry = ToolRegistry(
        confirmation,
        search_tool=lambda action: calls.append(action) or ["result"],
    )

    result = registry.dispatch(search_action())

    assert result.ok is True
    assert result.data == ["result"]
    assert calls == [search_action()]
    assert confirmation.requests[0].action == "refine_search"
    assert "Filters" not in dict(confirmation.requests[0].details)
    assert "Excludes" not in dict(confirmation.requests[0].details)


def test_default_search_passes_only_the_deterministic_source_scope(monkeypatch):
    calls = []

    def fake_search(query, **kwargs):
        calls.append((query, kwargs))
        return ["result"]

    monkeypatch.setattr(search_module, "search", fake_search)
    confirmation = RecordingConfirmation(approved=True)
    registry = ToolRegistry(confirmation)
    action = AgentAction(
        action="refine_search",
        reason="The user requested a YouTube search.",
        query="L vs Epistein",
        search_scope="youtube",
    )

    result = registry.dispatch(action)

    assert result.ok is True
    assert calls == [("L vs Epistein", {"source_scope": "youtube"})]
    assert dict(confirmation.requests[0].details)["Sources"] == "YouTube"


def test_rejected_download_never_calls_the_download_adapter():
    confirmation = RecordingConfirmation(approved=False)
    calls = []
    action = AgentAction(
        action="download_media",
        reason="The user provided a media URL.",
        url="https://example.com/video",
    )
    registry = ToolRegistry(
        confirmation,
        download_tool=lambda action: calls.append(action) or True,
    )

    result = registry.dispatch(action)

    assert result.ok is False
    assert result.cancelled is True
    assert calls == []


def test_respond_does_not_request_confirmation():
    confirmation = RecordingConfirmation(approved=False)
    registry = ToolRegistry(confirmation)
    action = AgentAction(
        action="respond",
        reason="No external action is needed.",
        message="Hello there.",
    )

    result = registry.dispatch(action)

    assert result.ok is True
    assert result.message == "Hello there."
    assert confirmation.requests == []


def test_unavailable_optional_tool_is_reported_before_confirmation():
    confirmation = RecordingConfirmation(approved=True)
    registry = ToolRegistry(confirmation)
    action = AgentAction(
        action="reverse_image_search",
        reason="The user requested reverse search.",
        image_path="C:/image.jpg",
    )

    with pytest.raises(ToolUnavailableError, match="reverse_image_search"):
        registry.dispatch(action)

    assert confirmation.requests == []


def test_configured_username_osint_adapter_runs_after_confirmation():
    confirmation = RecordingConfirmation(approved=True)
    calls = []
    action = AgentAction(
        action="username_osint",
        reason="The user explicitly requested a username lookup.",
        username="alice",
    )
    registry = ToolRegistry(
        confirmation,
        username_osint_tool=lambda received: calls.append(received) or [{"found": True}],
    )

    result = registry.dispatch(action)

    assert result.ok is True
    assert result.data == [{"found": True}]
    assert result.message == "Found 1 username result(s)."
    assert calls == [action]
    assert confirmation.requests[0].action == "username_osint"


def test_configured_email_osint_adapter_runs_after_confirmation():
    confirmation = RecordingConfirmation(approved=True)
    calls = []
    action = AgentAction(
        action="email_osint",
        reason="The user explicitly requested an email lookup.",
        email="alice@example.com",
    )
    registry = ToolRegistry(
        confirmation,
        email_osint_tool=lambda received: calls.append(received) or [{"site": "GitHub"}],
    )

    result = registry.dispatch(action)

    assert result.ok is True
    assert result.data == [{"site": "GitHub"}]
    assert result.message == "Found 1 email result(s)."
    assert calls == [action]
    assert confirmation.requests[0].action == "email_osint"
    assert dict(confirmation.requests[0].details)["Email"] == "alice@example.com"


def test_configured_reverse_image_adapter_runs_after_confirmation():
    confirmation = RecordingConfirmation(approved=True)
    calls = []
    action = AgentAction(
        action="reverse_image_search",
        reason="The user requested reverse search.",
        image_path="C:/image.jpg",
    )
    registry = ToolRegistry(
        confirmation,
        reverse_image_tool=lambda received: calls.append(received) or [{"url": "https://example.test"}],
    )

    result = registry.dispatch(action)

    assert result.ok is True
    assert result.data == [{"url": "https://example.test"}]
    assert result.message == "Found 1 reverse-image result(s)."
    assert calls == [action]


def test_reverse_image_search_resolves_missing_path_before_confirmation(tmp_path: Path):
    confirmation = RecordingConfirmation(approved=True)
    calls = []
    image_path = tmp_path / "selected.png"
    image_path.write_bytes(b"image")
    action = AgentAction(
        action="reverse_image_search",
        reason="The user requested reverse search.",
    )
    registry = ToolRegistry(
        confirmation,
        reverse_image_tool=lambda received: calls.append(received) or [{"url": "https://example.test"}],
        reverse_image_resolver=lambda: str(image_path),
    )

    result = registry.dispatch(action)

    assert result.ok is True
    assert dict(confirmation.requests[0].details)["Image"] == str(image_path)
    assert calls[0].image_path == str(image_path)


def test_reverse_image_search_cancels_when_resolver_returns_none():
    confirmation = RecordingConfirmation(approved=True)
    calls = []
    action = AgentAction(
        action="reverse_image_search",
        reason="The user requested reverse search.",
    )
    registry = ToolRegistry(
        confirmation,
        reverse_image_tool=lambda received: calls.append(received) or [],
        reverse_image_resolver=lambda: None,
    )

    result = registry.dispatch(action)

    assert result.ok is False
    assert result.cancelled is True
    assert confirmation.requests == []
    assert calls == []


def test_reverse_image_search_without_tool_stays_unavailable():
    confirmation = RecordingConfirmation(approved=True)
    registry = ToolRegistry(confirmation)
    action = AgentAction(
        action="reverse_image_search",
        reason="The user requested reverse search.",
        image_path="C:/image.jpg",
    )

    with pytest.raises(ToolUnavailableError, match="reverse_image_search"):
        registry.dispatch(action)


def test_reverse_image_search_without_resolver_stays_unavailable_for_missing_path():
    confirmation = RecordingConfirmation(approved=True)
    registry = ToolRegistry(confirmation)
    action = AgentAction(
        action="reverse_image_search",
        reason="The user requested reverse search.",
    )

    with pytest.raises(ToolUnavailableError, match="reverse_image_search"):
        registry.dispatch(action)

    assert confirmation.requests == []


def test_reverse_image_search_without_resolver_does_not_run_configured_adapter():
    confirmation = RecordingConfirmation(approved=True)
    calls = []
    registry = ToolRegistry(
        confirmation,
        reverse_image_tool=lambda received: calls.append(received) or [],
    )
    action = AgentAction(
        action="reverse_image_search",
        reason="The user requested reverse search.",
    )

    with pytest.raises(ToolUnavailableError, match="reverse_image_search"):
        registry.dispatch(action)

    assert confirmation.requests == []
    assert calls == []
