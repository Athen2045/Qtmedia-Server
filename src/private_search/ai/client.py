"""Small OpenAI-compatible client for the local llama.cpp server."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import urlparse


class LlamaClientError(RuntimeError):
    """Raised when the local chat endpoint cannot return a valid response."""


@dataclass(frozen=True)
class ChatCompletion:
    """The useful assistant fields returned by llama.cpp."""

    content: str
    reasoning_content: str
    model: str | None
    finish_reason: str | None
    raw: Mapping[str, object]


class LlamaClient:
    """Call an OpenAI-compatible llama.cpp server over loopback HTTP."""

    def __init__(
        self,
        base_url: str,
        *,
        opener: Callable[..., object] | None = None,
        timeout: float = 120.0,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise LlamaClientError("llama.cpp client must use a loopback endpoint")
        if timeout <= 0:
            raise LlamaClientError("llama.cpp client timeout must be positive")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._opener = opener or urllib.request.urlopen

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        enable_thinking: bool = False,
        response_format: Mapping[str, object] | None = None,
        allow_empty_content: bool = False,
    ) -> ChatCompletion:
        if not messages:
            raise LlamaClientError("at least one chat message is required")
        if max_tokens < 1:
            raise LlamaClientError("max_tokens must be positive")
        if temperature < 0:
            raise LlamaClientError("temperature cannot be negative")

        normalized_messages: list[dict[str, str]] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if not isinstance(role, str) or not role.strip():
                raise LlamaClientError("each chat message needs a role")
            if not isinstance(content, str):
                raise LlamaClientError("each chat message needs text content")
            normalized_messages.append({"role": role, "content": content})

        payload: dict[str, object] = {
            "messages": normalized_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        }
        if response_format is not None:
            payload["response_format"] = dict(response_format)

        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                raw_body = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise LlamaClientError(f"llama.cpp returned HTTP {error.code}: {detail}") from error
        except (OSError, urllib.error.URLError, TimeoutError) as error:
            raise LlamaClientError(f"llama.cpp request failed: {error}") from error

        try:
            raw = json.loads(raw_body)
        except (TypeError, json.JSONDecodeError) as error:
            raise LlamaClientError("llama.cpp returned invalid JSON") from error
        if not isinstance(raw, dict):
            raise LlamaClientError("llama.cpp returned a non-object response")

        try:
            choices = raw["choices"]
            choice = choices[0]
            message = choice["message"]
            content = message["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise LlamaClientError("llama.cpp response is missing assistant content") from error

        reasoning_content = message.get("reasoning_content", "")
        if not isinstance(reasoning_content, str):
            reasoning_content = ""
        if not isinstance(content, str):
            raise LlamaClientError("llama.cpp response has invalid assistant content")
        if not content.strip() and not allow_empty_content:
            raise LlamaClientError("llama.cpp response has empty assistant content")
        model = raw.get("model")
        if not isinstance(model, str):
            model = None
        finish_reason = choice.get("finish_reason")
        if not isinstance(finish_reason, str):
            finish_reason = None
        return ChatCompletion(
            content=content,
            reasoning_content=reasoning_content,
            model=model,
            finish_reason=finish_reason,
            raw=raw,
        )
