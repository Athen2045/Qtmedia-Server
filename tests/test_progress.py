from __future__ import annotations

import pytest

from private_search.progress import (
    ProgressEvent,
    format_progress_event,
    parse_progress_line,
)


def test_progress_event_round_trips_with_counts():
    event = ProgressEvent("scan", "Scanning sites", completed=42, total=716)

    assert parse_progress_line(format_progress_event(event)) == event


def test_progress_parser_accepts_phase_without_counts():
    assert parse_progress_line(
        'THEIA_PROGRESS {"phase":"upload","message":"Uploading image"}'
    ) == ProgressEvent("upload", "Uploading image")


@pytest.mark.parametrize(
    "line",
    [
        "ordinary diagnostic",
        'THEIA_PROGRESS {"phase":"scan"',
        'THEIA_PROGRESS {"phase":"","message":"bad"}',
        'THEIA_PROGRESS {"phase":"scan","completed":-1}',
        'THEIA_PROGRESS {"phase":"scan","total":0}',
    ],
)
def test_progress_parser_ignores_invalid_or_non_event_lines(line: str):
    assert parse_progress_line(line) is None
