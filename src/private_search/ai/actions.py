"""Strict model action protocol for the local chatbot."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse


class ActionValidationError(ValueError):
    """Raised when model output is not an allowed structured action."""


ALLOWED_ACTIONS = frozenset(
    {
        "respond",
        "refine_search",
        "download_media",
        "reverse_image_search",
        "username_osint",
        "describe_image",
    }
)

ACTION_SYSTEM_PROMPT = """You are Theia, the local assistant for a terminal search and download tool.
Theia is sharp, cheeky, and economical with words. She is a guide, not a
companion: help the user think and act faster rather than entertaining or
flattering them.
Use dry wit and confidence without flirtation. Be concise by default. Do not
add filler acknowledgments or restate the user's request. No emojis. No
exclamation-point enthusiasm. Use short, plain text-message-like phrasing
when it fits. Use decorative formatting only when structure genuinely helps.
Think like a hacker and security analyst: inspect attack surface, failure
modes, weak links, and what could go wrong. Stay realistic, flag uncertainty
plainly, and remain open to unconventional approaches when they are workable.
There is no flirtatious, suggestive, romantic, intimate, or adult-coded
framing toward the user. Never sexualize minors, coercion, exploitation, or
non-consensual activity. Never reveal hidden chain-of-thought.
Return exactly one JSON object and no Markdown. Never return shell commands.
Use only these actions: respond, refine_search, download_media,
reverse_image_search, username_osint, describe_image.
For a search request, always use refine_search with a non-empty query and
brief. Do not invent filters, exclusions, view thresholds, site names, or
source/type expressions. The application selects search sources from words
such as porn or youtube in the user's original request. Do not use the
respond action for a search request. Use the respond action only for normal
conversation and always include a non-empty message with it.
For a supplied http or https media URL, use download_media. For a request to
reverse-search an image, use reverse_image_search and leave image_path null if
the application must pick from the project image folder. do not invent paths.
For an explicit username lookup, use username_osint with username. For
describing a local image, use describe_image with image_path.
Always include every JSON field listed in the schema. Use null for an
irrelevant scalar field.
The application will validate your object and ask the user for confirmation
before any download, external search, reverse image search, or username OSINT.
"""

ACTION_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "action",
        "reason",
        "message",
        "query",
        "url",
        "image_path",
        "username",
        "brief",
    ],
    "properties": {
        "action": {"type": "string", "enum": sorted(ALLOWED_ACTIONS)},
        "reason": {"type": "string"},
        "message": {"type": ["string", "null"]},
        "query": {"type": ["string", "null"]},
        "url": {"type": ["string", "null"]},
        "image_path": {"type": ["string", "null"]},
        "username": {"type": ["string", "null"]},
        "brief": {"type": "boolean"},
    },
}

_ALLOWED_FIELDS = frozenset(ACTION_JSON_SCHEMA["properties"])
_WORD_TOKEN_PATTERN = re.compile(r"\b\w+\b")


@dataclass(frozen=True)
class AgentAction:
    """Validated action data; no field contains an executable command."""

    action: str
    reason: str
    message: str | None = None
    query: str | None = None
    url: str | None = None
    image_path: str | None = None
    username: str | None = None
    # Filled deterministically from the user's original search wording, not
    # from model output. This keeps source selection outside the tool protocol.
    search_scope: str | None = None
    brief: bool = False


def is_reverse_image_request(text: str) -> bool:
    """True when both reverse and search appear as word tokens."""

    tokens = {match.group(0).casefold() for match in _WORD_TOKEN_PATTERN.finditer(text)}
    return "reverse" in tokens and "search" in tokens


def _clean_text(value: object, field: str, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        requirement = "required" if required else "must be text"
        raise ActionValidationError(f"{field} {requirement}")
    return value.strip()


def _clean_http_url(value: object) -> str:
    url = _clean_text(value, "url", required=True)
    assert url is not None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ActionValidationError("url must be an http or https URL")
    return url


def _json_text(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) < 3:
            raise ActionValidationError("action JSON fence is empty")
        lines = lines[1:-1]
        if lines and lines[0].strip().casefold() == "json":
            lines = lines[1:]
        text = "\n".join(lines).strip()
    return text


def parse_action(raw_text: str) -> AgentAction:
    """Parse and validate one model-generated JSON action."""

    try:
        payload = json.loads(_json_text(raw_text))
    except (TypeError, json.JSONDecodeError) as error:
        raise ActionValidationError("model output must be a JSON object") from error
    if not isinstance(payload, dict):
        raise ActionValidationError("model output must be a JSON object")

    unknown = set(payload) - _ALLOWED_FIELDS
    if unknown:
        raise ActionValidationError(f"unknown action field: {min(unknown)}")
    action = _clean_text(payload.get("action"), "action", required=True)
    reason = _clean_text(payload.get("reason"), "reason", required=True)
    assert action is not None and reason is not None
    if action not in ALLOWED_ACTIONS:
        raise ActionValidationError(f"unknown action: {action}")

    brief = payload.get("brief", False)
    if not isinstance(brief, bool):
        raise ActionValidationError("brief must be a boolean")
    message = _clean_text(payload.get("message"), "message")
    query = _clean_text(payload.get("query"), "query")
    image_path = _clean_text(payload.get("image_path"), "image_path")
    username = _clean_text(payload.get("username"), "username")
    url = _clean_http_url(payload.get("url")) if payload.get("url") is not None else None

    if action == "respond" and message is None:
        raise ActionValidationError("message is required for respond")
    if action == "refine_search" and query is None:
        raise ActionValidationError("query is required for refine_search")
    if action == "download_media" and url is None:
        raise ActionValidationError("url is required for download_media")
    if action == "describe_image" and image_path is None:
        raise ActionValidationError(f"image_path is required for {action}")
    if action == "username_osint" and username is None:
        raise ActionValidationError("username is required for username_osint")

    return AgentAction(
        action=action,
        reason=reason,
        message=message,
        query=query,
        url=url,
        image_path=image_path,
        username=username,
        brief=brief,
    )
