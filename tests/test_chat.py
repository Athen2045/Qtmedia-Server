from __future__ import annotations

from private_search.ai.actions import AgentAction
from private_search.ai.chat import ChatOrchestrator, ChatTurnResult
from private_search.ai.client import ChatCompletion
from private_search.ai.tools import ToolResult


class FakeClient:
    def __init__(self, content: str | list[str]):
        self.content = content
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if isinstance(self.content, list):
            content = self.content.pop(0)
        else:
            content = self.content
        return ChatCompletion(
            content=content,
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


def test_chat_orchestrator_fails_closed_for_invalid_explicit_tool_request():
    client = FakeClient("not json")
    registry = FakeRegistry(ToolResult("respond", True, "unused"))
    chat = ChatOrchestrator(client, registry)

    result = chat.handle("download https://example.test/video")

    assert result.error is not None
    assert "JSON" in result.error
    assert registry.actions == []
    assert len(client.calls) == 2


def test_chat_orchestrator_recovers_invalid_classifier_for_non_tool_request():
    client = FakeClient(["not json", "still not json", "Natural answer."])
    registry = FakeRegistry(ToolResult("respond", True, "unused"))
    chat = ChatOrchestrator(client, registry)

    result = chat.handle("Write a C program that checks palindromes")

    assert result.error is None
    assert result.assistant_text == "Natural answer."
    assert registry.actions == []
    assert len(client.calls) == 3


def test_chat_orchestrator_keeps_only_recent_messages():
    client = FakeClient([action_json("respond", message="ok"), "ok"] * 3)
    registry = FakeRegistry(ToolResult("respond", True, "ok"))
    chat = ChatOrchestrator(client, registry, max_history=2)

    chat.handle("one")
    chat.handle("two")
    chat.handle("three")

    messages, _ = client.calls[-1]
    assert [message["content"] for message in messages[1:]] == ["two", "ok", "three"]


def test_chat_orchestrator_uses_freeform_lane_for_casual_and_code_requests():
    client = FakeClient(
        [
            action_json("respond", message="classifier placeholder"),
            "Here is the code:\n\n```python\nprint('hello')\n```",
        ]
    )
    registry = FakeRegistry(ToolResult("respond", True, "unused"))
    chat = ChatOrchestrator(client, registry, thinking_enabled=True)

    result = chat.handle("Write a small Python example")

    assert result.error is None
    assert result.assistant_text.startswith("Here is the code:")
    assert registry.actions == []
    assert client.calls[1][1]["enable_thinking"] is True
    assert client.calls[1][1]["max_tokens"] == 4096
    assert "response_format" not in client.calls[1][1]


def test_chat_orchestrator_retries_without_thinking_when_final_content_is_empty():
    client = FakeClient(
        [
            action_json("respond", message="classifier placeholder"),
            "",
            "Fallback answer.",
        ]
    )
    registry = FakeRegistry(ToolResult("respond", True, "unused"))
    chat = ChatOrchestrator(client, registry, thinking_enabled=True)

    result = chat.handle("hey")

    assert result.error is None
    assert result.assistant_text == "Fallback answer."
    assert client.calls[1][1]["enable_thinking"] is True
    assert client.calls[2][1]["enable_thinking"] is False


def test_chat_orchestrator_can_disable_thinking_for_freeform_answers():
    client = FakeClient(
        [
            action_json("respond", message="classifier placeholder"),
            "Direct answer.",
        ]
    )
    chat = ChatOrchestrator(
        client,
        FakeRegistry(ToolResult("respond", True, "unused")),
    )

    assert chat.thinking_enabled is False
    chat.set_thinking(False)
    result = chat.handle("answer directly")

    assert result.assistant_text == "Direct answer."
    assert chat.thinking_enabled is False
    assert client.calls[1][1]["enable_thinking"] is False
    assert len(client.calls) == 2


def test_chat_orchestrator_tracks_llama_context_usage():
    class UsageClient(FakeClient):
        def complete(self, messages, **kwargs):
            completion = super().complete(messages, **kwargs)
            return ChatCompletion(
                content=completion.content,
                reasoning_content=completion.reasoning_content,
                model=completion.model,
                finish_reason=completion.finish_reason,
                raw={"usage": {"prompt_tokens": 900, "completion_tokens": 100}},
            )

    client = UsageClient(action_json("refine_search", query="needle"))
    chat = ChatOrchestrator(
        client,
        FakeRegistry(ToolResult("refine_search", True, "No results.")),
        context_window=8192,
    )

    chat.handle("search for needle")

    assert chat.context_usage.used == 1000
    assert chat.context_usage.remaining == 7192
    assert chat.context_usage.total == 8192
    assert chat.context_usage.exact is True
