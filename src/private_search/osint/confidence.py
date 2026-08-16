"""Score normalization and confidence filtering."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping


def normalize_score(value: object, *, source: str) -> float | None:
    """Return a presentation score in the 0..100 range, or ``None``."""

    number = _coerce_number(value)
    if number is None:
        return None

    score = number * 100.0 if abs(number) <= 1.0 else number
    if score < 0.0:
        return 0.0
    if score > 100.0:
        return 100.0
    return float(score)


def confidence_band(score: float) -> str:
    """Map a presentation score to one of the three UI bands."""

    if score >= 90.0:
        return "Accurate"
    if score >= 75.0:
        return "More likely"
    return "Possible"


def filter_confident(
    results: Iterable[Mapping[str, object]],
    *,
    field: str = "confidence",
    minimum: float = 75.0,
) -> list[dict[str, object]]:
    """Drop records whose parsed score falls below the threshold."""

    filtered: list[dict[str, object]] = []
    for result in results:
        score = normalize_score(result.get(field), source=field)
        if score is not None and score < minimum:
            continue
        filtered.append(dict(result))
    return filtered


def _coerce_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        return None

    if not math.isfinite(number):
        return None
    return number

