from __future__ import annotations

from private_search.ai.actions import AgentAction
from private_search.ai.chat import ChatOrchestrator, ChatTurnResult
from private_search.ai.client import ChatCompletion
from private_search.ai.tools import ToolResult


class FakeClient:
    def __init__(self, content: str):
        self.content = content
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return ChatCompletion(
            content=self.content,
            reasoning_content="",
            model="fake",
            finish_reason="stop",
            raw={},
        )


class FakeRegistry:
    def __init__(self, result: ToolResult):
        self.result = result
        self.actions = []

    def dispatch(self, action: AgentAction) -> ToolResult:
        self.actions.append(action)
        return self.result


def action_json(action: str, **fields) -> str:
    import json

    payload = {
        "action": action,
        "reason": "The user requested this action.",
        "message": None,
        "query": None,
        "url": None,
        "image_path": None,
        "username": None,
        "email": None,
        "brief": False,
    }
    payload.update(fields)
    return json.dumps(payload)


def test_chat_orchestrator_dispatches_a_valid_search_action():
    client = FakeClient(
        action_json(
            "refine_search",
            query="Bimbo PMV",
        )
    )
    registry = FakeRegistry(
        ToolResult("refine_search", True, "Found 2 search result(s).", data=["a", "b"])
    )
    chat = ChatOrchestrator(client, registry)

    result = chat.handle("Search for Bimbo Pmv")

    assert isinstance(result, ChatTurnResult)
    assert result.error is None
    assert result.action is not None
    assert result.action.query == "Bimbo PMV"
    assert result.tool_result is registry.result
    assert result.assistant_text == "Found 2 search result(s)."
    assert registry.actions == [result.action]


def test_chat_orchestrator_routes_explicit_youtube_keyword():
    client = FakeClient(action_json("refine_search", query="wrong model query"))
    registry = FakeRegistry(ToolResult("refine_search", True, "Found 1 search result."))
    chat = ChatOrchestrator(client, registry)

    result = chat.handle("Search YOUTUBE 'L vs Epistein'")

    assert result.error is None
    assert result.action is not None
    assert result.action.query == "L vs Epistein"
    assert result.action.search_scope == "youtube"


def test_chat_orchestrator_forces_reverse_search_from_user_keywords():
    client = FakeClient(
        action_json(
            "respond",
            message="wrong action",
            query="wrong query",
            url="https://example.com/image",
            image_path="C:/model-supplied.jpg",
            username="alice",
            email="alice@example.com",
        )
    )
    registry = FakeRegistry(
        ToolResult("reverse_image_search", True, "Found 1 reverse-image result(s).")
    )
    chat = ChatOrchestrator(client, registry, max_history=2)

    result = chat.handle("Please reverse search this image")

    messages, kwargs = client.calls[0]
    assert result.error is None
    assert result.action is not None
    assert result.action.action == "reverse_image_search"
    assert result.action.message is None
    assert result.action.query is None
    assert result.action.url is None
    assert result.action.image_path is None
    assert result.action.username is None
    assert result.action.email is None
    assert messages[-1] == {"role": "user", "content": "Please reverse search this image"}
    assert kwargs["enable_thinking"] is False
    assert kwargs["response_format"]["type"] == "json_schema"


def test_chat_orchestrator_returns_validation_error_without_dispatch():
    client = FakeClient("not json")
    registry = FakeRegistry(ToolResult("respond", True, "unused"))
    chat = ChatOrchestrator(client, registry)

    result = chat.handle("do something")

    assert result.error is not None
    assert "JSON" in result.error
    assert registry.actions == []


def test_chat_orchestrator_keeps_only_recent_messages():
    client = FakeClient(action_json("respond", message="ok"))
    registry = FakeRegistry(ToolResult("respond", True, "ok"))
    chat = ChatOrchestrator(client, registry, max_history=2)

    chat.handle("one")
    chat.handle("two")
    chat.handle("three")

    messages, _ = client.calls[-1]
    assert [message["content"] for message in messages[1:]] == ["two", "ok", "three"]
