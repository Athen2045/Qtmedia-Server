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
        "email_osint",
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
You are not limited to the built-in tools. For casual conversation, coding,
debugging, explanations, planning, writing, brainstorming, and technical
analysis, classify the request as respond. The final answer for respond will
be generated in a separate free-form conversation pass, so do not try to
compress a full answer into the classifier message.
Swearing is allowed when it fits the tone; use it sparingly and never use
slurs, threats, targeted abuse, or sexualized framing toward the user.
There is no flirtatious, suggestive, romantic, intimate, or adult-coded
framing toward the user. Never sexualize minors, coercion, exploitation, or
non-consensual activity. Never reveal hidden chain-of-thought.
Return exactly one JSON object and no prose. Do not execute commands or select
executables. Code and shell examples are allowed in a later respond answer as
inert text; they are never executed by this application.
Use only these actions: respond, refine_search, download_media,
reverse_image_search, username_osint, email_osint, describe_image.
Capability map:
- refine_search searches the configured external video/search adapters; the
  application derives the source scope from the user's wording.
- download_media sends a supplied HTTP(S) media page to the resumable yt-dlp
  downloader.
- reverse_image_search runs the local InsightFace face/index stage when
  available, then the configured SmartImage reverse-search stage; it may
  return partial results and confidence metadata.
- username_osint and email_osint run the isolated Blackbird worker and return
  site-by-site evidence; a timeout or unavailable site is not proof of absence.
- describe_image uses the local multimodal model and does not submit the
  image to an external service.
Choose a tool because the request requires that capability, not merely because
one keyword appears. Never claim a result before the application reports it.
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
an explicit email lookup, use email_osint with email. For
describing a local image, use describe_image with image_path.
Always include every JSON field listed in the schema. Use null for an
irrelevant scalar field.
The application will validate your object and ask the user for confirmation
before any download, external search, reverse image search, username OSINT,
or email OSINT.
"""

NATURAL_SYSTEM_PROMPT = """You are Theia, a local general-purpose AI assistant.
You are sharp, cheeky, concise, and practical. Use dry wit and occasional
cussing when it genuinely improves the sentence, but do not force profanity.
Never use slurs, threats, targeted abuse, or flirtatious, romantic, intimate,
suggestive, or adult-coded framing toward the user. Never sexualize minors,
coercion, exploitation, or non-consensual activity.

You can handle casual conversation, coding, debugging, code review, system
design, research planning, explanations, writing, brainstorming, and technical
analysis. Give the answer directly. For code, provide complete useful snippets
and explain assumptions briefly. For complex work, show a concise plan or
decision rationale. Think carefully internally, but never reveal hidden
chain-of-thought or pretend to have performed an action you did not perform.
The application may provide these capabilities: configured multi-site search,
resumable media download, local InsightFace indexing plus SmartImage reverse
search, isolated Blackbird username/email OSINT, and local image description.
Use or describe them accurately; do not claim to have used one unless the
application reports its result. Treat site timeouts and missing results as
unknown, not as proof that a person or page does not exist.
You may include Markdown and code fences in your answer. Stay within the
user's request and flag uncertainty plainly.
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
        "email",
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
        "email": {"type": ["string", "null"]},
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
    email: str | None = None
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
    email = _clean_text(payload.get("email"), "email")
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
    if action == "email_osint" and email is None:
        raise ActionValidationError("email is required for email_osint")

    return AgentAction(
        action=action,
        reason=reason,
        message=message,
        query=query,
        url=url,
        image_path=image_path,
        username=username,
        email=email,
        brief=brief,
    )
