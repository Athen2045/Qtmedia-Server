from __future__ import annotations

import json

import pytest

from qtmedia_engine.protocol import ProtocolError, encode_event, parse_request


def test_parse_request_accepts_probe_and_inspect():
    assert parse_request('{"id":"probe","action":"probe"}').action == "probe"
    inspected = parse_request(
        '{"id":"r1","action":"inspect","url":"https://source.invalid/item"}'
    )
    assert inspected.request_id == "r1"
    assert inspected.payload["url"] == "https://source.invalid/item"
    download = parse_request(
        '{"id":"r2","action":"download","media_id":"m","format_key":"format-fixture"}'
    )
    assert download.payload["format_key"] == "format-fixture"


@pytest.mark.parametrize(
    "line",
    [
        "not-json",
        "[]",
        '{"id":"r1","action":"shell"}',
        '{"id":"","action":"probe"}',
    ],
)
def test_parse_request_rejects_malformed_and_unknown_requests(line: str):
    with pytest.raises(ProtocolError):
        parse_request(line)


@pytest.mark.parametrize(
    "line",
    [
        '{"id":"r1","action":"probe","url":"https://private.invalid/item"}',
        '{"id":"r1","action":"download","media_id":"m","kind":"video"}',
        '{"id":"r1","action":"download","media_id":"m","format_key":""}',
        '{"id":"r1","action":"inspect","url":"https://source.invalid/item","extra":"not-allowed"}',
    ],
)
def test_only_inspect_may_carry_exactly_one_raw_url(line: str):
    with pytest.raises(ProtocolError):
        parse_request(line)


def test_encode_event_never_serializes_source_url_or_raw_detail():
    encoded = encode_event(
        request_id="r1",
        event="error",
        payload={
            "code": "download_failed",
            "url": "https://private.invalid/item",
            "detail": "provider response",
        },
    )
    decoded = json.loads(encoded)

    assert decoded == {"id": "r1", "event": "error", "code": "download_failed"}
    assert "private.invalid" not in encoded


def test_events_survive_windows_pipe_encoding_without_losing_unicode():
    payload = {"title": "Music 日本語 🎵", "formats": [{"label": "MP3 · 192 kbps"}]}
    encoded = encode_event("inspect-1", "inspection_ready", payload)
    # Windows pipes may default to a legacy code page. ASCII JSON is also
    # valid UTF-8, and JSON decoding restores the original display strings.
    wire = encoded.encode("cp1252")
    restored = json.loads(wire.decode("utf-8"))
    assert restored["title"] == "Music 日本語 🎵"
    assert restored["formats"][0]["label"] == "MP3 · 192 kbps"
