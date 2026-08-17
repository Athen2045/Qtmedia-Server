"""Model-to-action orchestration for the terminal chatbot."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace

from ..search.engine import parse_search_request
from .actions import (
    ACTION_JSON_SCHEMA,
    ACTION_SYSTEM_PROMPT,
    NATURAL_SYSTEM_PROMPT,
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


@dataclass(frozen=True)
class ContextUsage:
    """Current context-window usage exposed to the terminal UI."""

    used: int
    remaining: int
    total: int
    exact: bool


class ChatOrchestrator:
    """Keep chat context and connect validated model actions to the registry."""

    def __init__(
        self,
        client,
        registry: ToolRegistry,
        *,
        max_history: int = 12,
        context_window: int = 8192,
        thinking_enabled: bool = False,
    ) -> None:
        if max_history < 1:
            raise ValueError("max_history must be positive")
        if context_window < 1:
            raise ValueError("context_window must be positive")
        self._client = client
        self._registry = registry
        self._max_history = max_history
        self._context_window = context_window
        self._thinking_enabled = thinking_enabled
        self._last_context_tokens: int | None = None
        self._history: list[dict[str, str]] = []

    @property
    def history(self) -> tuple[Mapping[str, str], ...]:
        return tuple(self._history)

    @property
    def thinking_enabled(self) -> bool:
        return self._thinking_enabled

    @property
    def context_usage(self) -> ContextUsage:
        estimated = self._estimate_retained_tokens()
        exact = self._last_context_tokens is not None
        used = self._last_context_tokens if exact else estimated
        used = max(0, min(used, self._context_window))
        return ContextUsage(
            used=used,
            remaining=max(0, self._context_window - used),
            total=self._context_window,
            exact=exact,
        )

    def set_thinking(self, enabled: bool) -> None:
        self._thinking_enabled = bool(enabled)

    def execute_action(self, action: AgentAction):
        """Execute a validated UI-created action through the tool registry."""

        return self._registry.dispatch(action)

    def handle(self, user_text: str) -> ChatTurnResult:
        cleaned = user_text.strip()
        if not cleaned:
            return ChatTurnResult(user_text=user_text, error="Enter a message.")

        action: AgentAction | None = None
        try:
            action = self._classify_action(cleaned)
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
            if action.action == "respond":
                assistant_text = self._complete_natural_response(cleaned)
                tool_result = ToolResult(
                    action="respond",
                    ok=True,
                    message=assistant_text,
                )
            else:
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

    def _classify_action(self, user_text: str) -> AgentAction:
        first_error: ActionValidationError | None = None
        for strict_retry in (False, True):
            messages = self._messages_for(user_text)
            if strict_retry:
                messages[0] = {
                    "role": "system",
                    "content": (
                        ACTION_SYSTEM_PROMPT
                        + "\nYour previous classification was invalid. Return exactly one "
                        "JSON object matching the schema. No prose or Markdown."
                    ),
                }
            completion = self._client.complete(
                messages,
                temperature=0.0,
                enable_thinking=False,
                max_tokens=384,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "agent_action", "schema": ACTION_JSON_SCHEMA},
                },
            )
            self._record_usage(completion)
            try:
                return parse_action(completion.content)
            except ActionValidationError as error:
                first_error = error

        if not self._requires_tool_classification(user_text):
            return AgentAction(
                action="respond",
                reason="The strict classifier failed; this request has no explicit tool intent.",
                message="Generate a normal conversational response.",
            )
        assert first_error is not None
        raise first_error

    @staticmethod
    def _requires_tool_classification(user_text: str) -> bool:
        text = user_text.casefold().strip()
        if re.search(r"https?://\S+", text):
            return True
        if is_reverse_image_request(text):
            return True
        if re.match(r"^(?:search|find)(?:\s+for)?\b", text):
            return True
        if re.search(r"\b(?:download|save media|grab media)\b", text):
            return True
        subject = r"(?:username|email)"
        operation = r"(?:search|lookup|look up|check|osint|find)"
        return bool(
            re.search(rf"\b{operation}\b.*\b{subject}\b", text)
            or re.search(rf"\b{subject}\b.*\b{operation}\b", text)
        )

    def _complete_natural_response(self, user_text: str) -> str:
        if not self._thinking_enabled:
            completion = self._client.complete(
                self._natural_messages_for(user_text),
                temperature=0.45,
                max_tokens=4096,
                enable_thinking=False,
            )
            self._record_usage(completion)
            response = completion.content.strip()
            if not response:
                raise LlamaClientError("Theia returned an empty conversation response")
            return response

        completion = self._client.complete(
            self._natural_messages_for(user_text),
            temperature=0.45,
            max_tokens=4096,
            enable_thinking=True,
            allow_empty_content=True,
        )
        self._record_usage(completion)
        response = completion.content.strip()
        if not response:
            completion = self._client.complete(
                self._natural_messages_for(user_text),
                temperature=0.45,
                max_tokens=4096,
                enable_thinking=False,
            )
            self._record_usage(completion)
            response = completion.content.strip()
        if not response:
            raise LlamaClientError("Theia returned an empty conversation response")
        return response

    def _record_usage(self, completion) -> None:
        usage = completion.raw.get("usage") if isinstance(completion.raw, Mapping) else None
        if not isinstance(usage, Mapping):
            return
        total_tokens = usage.get("total_tokens")
        if isinstance(total_tokens, int) and not isinstance(total_tokens, bool):
            self._last_context_tokens = max(0, total_tokens)
            return
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (prompt_tokens, completion_tokens)
        ):
            self._last_context_tokens = max(0, prompt_tokens + completion_tokens)

    def _estimate_retained_tokens(self) -> int:
        # Four characters per token plus a small per-message template allowance
        # is intentionally presented as an estimate, never as tokenizer truth.
        messages = [NATURAL_SYSTEM_PROMPT, *(item["content"] for item in self._history)]
        return sum(max(1, (len(message) + 3) // 4) + 4 for message in messages)

    def _messages_for(self, user_text: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": ACTION_SYSTEM_PROMPT},
            *self._history,
            {"role": "user", "content": user_text},
        ]

    def _natural_messages_for(self, user_text: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": NATURAL_SYSTEM_PROMPT},
            *self._history,
            {"role": "user", "content": user_text},
        ]
