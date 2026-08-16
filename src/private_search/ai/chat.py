"""Model-to-action orchestration for the terminal chatbot."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from ..search.engine import parse_search_request
from .actions import (
    ACTION_JSON_SCHEMA,
    ACTION_SYSTEM_PROMPT,
    ActionValidationError,
    AgentAction,
    is_reverse_image_request,
    parse_action,
)
from .client import LlamaClientError
from .tools import ToolExecutionError, ToolRegistry, ToolResult, ToolUnavailableError


@dataclass(frozen=True)
class ChatTurnResult:
    """The model action and tool outcome for one user message."""

    user_text: str
    action: AgentAction | None = None
    tool_result: ToolResult | None = None
    assistant_text: str = ""
    error: str | None = None


class ChatOrchestrator:
    """Keep chat context and connect validated model actions to the registry."""

    def __init__(self, client, registry: ToolRegistry, *, max_history: int = 12) -> None:
        if max_history < 1:
            raise ValueError("max_history must be positive")
        self._client = client
        self._registry = registry
        self._max_history = max_history
        self._history: list[dict[str, str]] = []

    @property
    def history(self) -> tuple[Mapping[str, str], ...]:
        return tuple(self._history)

    def execute_action(self, action: AgentAction):
        """Execute a validated UI-created action through the tool registry."""

        return self._registry.dispatch(action)

    def handle(self, user_text: str) -> ChatTurnResult:
        cleaned = user_text.strip()
        if not cleaned:
            return ChatTurnResult(user_text=user_text, error="Enter a message.")

        action: AgentAction | None = None
        try:
            completion = self._client.complete(
                self._messages_for(cleaned),
                enable_thinking=False,
                max_tokens=256,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "agent_action", "schema": ACTION_JSON_SCHEMA},
                },
            )
            action = parse_action(completion.content)
            if is_reverse_image_request(cleaned):
                action = replace(
                    action,
                    action="reverse_image_search",
                    message=None,
                    query=None,
                    url=None,
                    image_path=None,
                    username=None,
                    email=None,
                    search_scope=None,
                )
            if action.action == "refine_search":
                request = parse_search_request(cleaned, action.query or "")
                action = replace(
                    action,
                    query=request.query,
                    search_scope=request.scope,
                )
            tool_result = self.execute_action(action)
        except (
            ActionValidationError,
            LlamaClientError,
            ToolExecutionError,
            ToolUnavailableError,
        ) as error:
            return ChatTurnResult(user_text=cleaned, action=action, error=str(error))

        assistant_text = tool_result.message
        self._history.extend(
            [
                {"role": "user", "content": cleaned},
                {"role": "assistant", "content": assistant_text},
            ]
        )
        del self._history[:-self._max_history]
        return ChatTurnResult(
            user_text=cleaned,
            action=action,
            tool_result=tool_result,
            assistant_text=assistant_text,
        )

    def _messages_for(self, user_text: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": ACTION_SYSTEM_PROMPT},
            *self._history,
            {"role": "user", "content": user_text},
        ]
