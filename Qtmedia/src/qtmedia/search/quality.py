"""Text normalization, filtering, and relevance scoring for search results."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from rapidfuzz import fuzz

TOKEN_PATTERN = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)


def normalize_text(text: str) -> str:
    """Return a stable, Unicode-aware representation used for matching."""
    return " ".join(tokenize(unicodedata.normalize("NFKC", text)))


def tokenize(text: str) -> tuple[str, ...]:
    """Split text into case-folded Unicode word tokens."""
    folded = text.casefold()
    return tuple(match.group(0) for match in TOKEN_PATTERN.finditer(folded))


def _contains_contiguous(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    width = len(needle)
    return any(haystack[index : index + width] == needle for index in range(len(haystack) - width + 1))


def term_matches(text: str, term: str) -> bool:
    """Return whether a word or phrase occurs without substring false positives."""
    text_tokens = tokenize(text)
    term_tokens = tokenize(term)
    return _contains_contiguous(text_tokens, term_tokens)


def relevance_score(title: str, query: str) -> tuple[float, ...]:
    """Score a title from strongest exact signals to bounded fuzzy signals.

    Earlier tuple fields are more important than later fields. Keeping the
    score as a tuple makes ranking deterministic and cheap for small remote
    result sets while RapidFuzz handles the edit-distance work in native code.
    """
    normalized_title = normalize_text(title)
    normalized_query = normalize_text(query)
    if not normalized_query:
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    query_tokens = tokenize(normalized_query)
    title_tokens = tokenize(normalized_title)
    title_token_set = set(title_tokens)
    covered = sum(token in title_token_set for token in query_tokens)
    coverage = covered / len(query_tokens) if query_tokens else 0.0
    exact_title = float(normalized_title == normalized_query)
    exact_phrase = float(_contains_contiguous(title_tokens, query_tokens))
    all_tokens = float(bool(query_tokens) and covered == len(query_tokens))
    token_sort = fuzz.token_sort_ratio(normalized_query, normalized_title) / 100.0
    partial = fuzz.partial_ratio(normalized_query, normalized_title) / 100.0
    return (exact_title, exact_phrase, all_tokens, coverage, token_sort, partial)


def rank_titles(titles: Iterable[str], query: str) -> list[str]:
    """Return titles in relevance order, preserving input order for ties."""
    return sorted(titles, key=lambda title: relevance_score(title, query), reverse=True)
