from __future__ import annotations

from private_search.osint.confidence import (
    confidence_band,
    filter_confident,
    normalize_score,
)


def test_normalize_score_parses_fractional_and_percent_inputs():
    assert normalize_score(0.82, source="smartimage") == 82.0
    assert normalize_score(82, source="smartimage") == 82.0


def test_normalize_score_rejects_empty_and_non_finite_values():
    assert normalize_score("", source="smartimage") is None
    assert normalize_score("   ", source="smartimage") is None
    assert normalize_score(float("nan"), source="smartimage") is None
    assert normalize_score(float("inf"), source="smartimage") is None


def test_normalize_score_clamps_to_presentation_bounds():
    assert normalize_score(-5, source="smartimage") == 0.0
    assert normalize_score(125, source="smartimage") == 100.0


def test_confidence_band_groups_scores_into_three_bands():
    assert confidence_band(95) == "Accurate"
    assert confidence_band(80) == "More likely"
    assert confidence_band(74.9) == "Possible"


def test_filter_confident_drops_numeric_scores_below_threshold_and_keeps_order():
    results = [
        {"id": "first", "confidence": 91},
        {"id": "second", "confidence": 74.9},
        {"id": "third", "confidence": 75},
        {"id": "fourth", "confidence": "n/a"},
    ]

    filtered = filter_confident(results)

    assert filtered == [
        {"id": "first", "confidence": 91},
        {"id": "third", "confidence": 75},
        {"id": "fourth", "confidence": "n/a"},
    ]
