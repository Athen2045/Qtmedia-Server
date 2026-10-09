"""Strict request parsing and privacy-safe event serialization."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

ALLOWED_ACTIONS = frozenset({"probe", "inspect", "download", "cancel", "library_list"})
ACTION_FIELDS = {
    "probe": frozenset(),
    "inspect": frozenset({"url"}),
    "download": frozenset({"media_id", "format_key"}),
    "cancel": frozenset({"job_id"}),
    "library_list": frozenset(),
}
EVENT_FIELDS = frozenset(
    {
        "code",
        "media_id",
        "job_id",
        "site",
        "title",
        "duration_seconds",
        "formats",
        "downloaded_bytes",
        "total_bytes",
        "percent",
        "entry",
        "entries",
        "status",
    }
)


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class Request:
    request_id: str
    action: str
    payload: dict[str, Any]


def parse_request(line: str) -> Request:
    try:
        value = json.loads(line)
    except json.JSONDecodeError as error:
        raise ProtocolError("malformed_json") from error
    if not isinstance(value, dict):
        raise ProtocolError("invalid_request")
    request_id = value.get("id")
    action = value.get("action")
    if not isinstance(request_id, str) or not request_id.strip():
        raise ProtocolError("invalid_request")
    if action not in ALLOWED_ACTIONS:
        raise ProtocolError("unknown_action")
    payload = {key: item for key, item in value.items() if key not in {"id", "action"}}
    if frozenset(payload) != ACTION_FIELDS[action]:
        raise ProtocolError("invalid_request")
    if action == "inspect" and not isinstance(payload.get("url"), str):
        raise ProtocolError("invalid_request")
    if action == "download" and (
        not isinstance(payload.get("media_id"), str)
        or not payload.get("media_id", "").strip()
        or not isinstance(payload.get("format_key"), str)
        or not payload.get("format_key", "").strip()
    ):
        raise ProtocolError("invalid_request")
    if action == "cancel" and not isinstance(payload.get("job_id"), str):
        raise ProtocolError("invalid_request")
    return Request(request_id=request_id, action=action, payload=payload)


def encode_event(
    request_id: str,
    event: str,
    payload: dict[str, Any] | None = None,
) -> str:
    safe = {
        key: value
        for key, value in (payload or {}).items()
        if key in EVENT_FIELDS
    }
    return json.dumps(
        {"id": request_id, "event": event, **safe},
        # ASCII escapes keep Windows legacy-code-page pipes valid UTF-8.
        # JSON receivers restore the original Unicode labels and titles.
        ensure_ascii=True,
        separators=(",", ":"),
    )
