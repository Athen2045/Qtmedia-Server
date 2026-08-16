from __future__ import annotations

import json

import pytest

from private_search.ai.actions import (
    ACTION_JSON_SCHEMA,
    ACTION_SYSTEM_PROMPT,
    ActionValidationError,
    AgentAction,
    is_reverse_image_request,
    parse_action,
)


def encode(payload: dict) -> str:
    return json.dumps(payload)


def test_action_prompt_maps_search_requests_to_refine_search():
    assert "search request" in ACTION_SYSTEM_PROMPT
    assert "refine_search" in ACTION_SYSTEM_PROMPT
    assert "respond action" in ACTION_SYSTEM_PROMPT
    assert "project image folder" in ACTION_SYSTEM_PROMPT
    assert "do not invent paths" in ACTION_SYSTEM_PROMPT
    assert "Theia" in ACTION_SYSTEM_PROMPT
    assert "sharp, cheeky" in ACTION_SYSTEM_PROMPT
    assert "economical with words" in ACTION_SYSTEM_PROMPT
    assert "hacker and security analyst" in ACTION_SYSTEM_PROMPT
    assert "No emoji" in ACTION_SYSTEM_PROMPT
    assert "no flirtatious, suggestive, romantic, intimate, or adult-coded" in ACTION_SYSTEM_PROMPT
    assert "flirtatious adult personality" not in ACTION_SYSTEM_PROMPT


def test_action_schema_requires_the_complete_canonical_object():
    assert set(ACTION_JSON_SCHEMA["required"]) == {
        "action",
        "reason",
        "message",
        "query",
        "url",
        "image_path",
        "username",
        "brief",
    }
    assert "filters" not in ACTION_JSON_SCHEMA["properties"]
    assert "excludes" not in ACTION_JSON_SCHEMA["properties"]
    assert "min_views" not in ACTION_JSON_SCHEMA["properties"]


def test_parse_download_action_requires_an_http_url():
    action = parse_action(
        encode(
            {
                "action": "download_media",
                "reason": "The user supplied a media link.",
                "url": "https://example.com/video",
                "brief": False,
            }
        )
    )

    assert isinstance(action, AgentAction)
    assert action.action == "download_media"
    assert action.url == "https://example.com/video"


def test_parse_search_action_contains_only_the_query_controls():
    action = parse_action(
        encode(
            {
                "action": "refine_search",
                "reason": "The phrase is a video search request.",
                "query": "Bimbo PMV",
                "brief": True,
            }
        )
    )

    assert action.query == "Bimbo PMV"
    assert action.brief is True


def test_parse_reverse_image_search_allows_missing_image_path_for_resolution():
    action = parse_action(
        encode(
            {
                "action": "reverse_image_search",
                "reason": "The user wants a reverse search.",
                "image_path": None,
                "brief": False,
            }
        )
    )

    assert action.action == "reverse_image_search"
    assert action.image_path is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("reverse search this", True),
        ("Please Reverse that SEARCH result", True),
        ("Use a reverse-search engine", True),
        ("search in reverse chronological order", True),
        ("find the reverse side of the photo", False),
    ],
)
def test_is_reverse_image_request_requires_both_words_as_tokens(
    text: str, expected: bool
):
    assert is_reverse_image_request(text) is expected


def test_parse_action_rejects_removed_search_controls():
    with pytest.raises(ActionValidationError, match="unknown action field"):
        parse_action(
            encode(
                {
                    "action": "refine_search",
                    "reason": "The phrase is a video search request.",
                    "query": "Bimbo PMV",
                    "filters": [],
                }
            )
        )


def test_parse_action_accepts_fenced_json():
    action = parse_action(
        "```json\n"
        + encode(
            {
                "action": "respond",
                "reason": "No external action is needed.",
                "message": "I can help with that.",
            }
        )
        + "\n```"
    )

    assert action.action == "respond"
    assert action.message == "I can help with that."


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"action": "run_shell", "reason": "unsafe"}, "unknown action"),
        ({"action": "download_media", "reason": "missing URL"}, "url"),
        (
            {"action": "download_media", "reason": "bad URL", "url": "file:///secret"},
            "http",
        ),
        ({"action": "username_osint", "reason": "missing username"}, "username"),
        ({"action": "respond", "reason": "missing message"}, "message"),
        (
            {"action": "describe_image", "reason": "missing image path"},
            "image_path",
        ),
    ],
)
def test_parse_action_rejects_invalid_or_unsafe_payloads(payload: dict, error: str):
    with pytest.raises(ActionValidationError, match=error):
        parse_action(encode(payload))
