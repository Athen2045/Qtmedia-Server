from __future__ import annotations

import json
from urllib.error import URLError

import pytest

from private_search.ai.client import ChatCompletion, LlamaClient, LlamaClientError


class FakeResponse:
    status = 200

    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None


def test_client_posts_non_thinking_chat_request():
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data)
        return FakeResponse(
            {
                "model": "local-qwen",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "hello"},
                        "finish_reason": "stop",
                    }
                ],
            }
        )

    client = LlamaClient("http://127.0.0.1:8080", opener=opener, timeout=12)

    result = client.complete(
        [{"role": "user", "content": "hello"}],
        enable_thinking=False,
        max_tokens=32,
    )

    assert isinstance(result, ChatCompletion)
    assert result.content == "hello"
    assert captured["url"] == "http://127.0.0.1:8080/v1/chat/completions"
    assert captured["timeout"] == 12
    assert captured["payload"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert captured["payload"]["max_tokens"] == 32


def test_client_rejects_non_loopback_endpoint():
    with pytest.raises(LlamaClientError, match="loopback"):
        LlamaClient("https://example.com")


def test_client_wraps_transport_errors():
    def opener(request, timeout):
        raise URLError("connection refused")

    client = LlamaClient("http://127.0.0.1:8080", opener=opener)

    with pytest.raises(LlamaClientError, match="connection refused"):
        client.complete([{"role": "user", "content": "hello"}])


def test_client_rejects_response_without_assistant_content():
    def opener(request, timeout):
        return FakeResponse({"choices": [{"message": {"role": "assistant", "content": ""}}]})

    client = LlamaClient("http://127.0.0.1:8080", opener=opener)

    with pytest.raises(LlamaClientError, match="assistant content"):
        client.complete([{"role": "user", "content": "hello"}])


def test_client_can_preserve_reasoning_only_response_for_safe_retry():
    def opener(request, timeout):
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "reasoning_content": "private reasoning",
                        }
                    }
                ]
            }
        )

    client = LlamaClient("http://127.0.0.1:8080", opener=opener)

    result = client.complete(
        [{"role": "user", "content": "hello"}],
        enable_thinking=True,
        allow_empty_content=True,
    )

    assert result.content == ""
    assert result.reasoning_content == "private reasoning"
