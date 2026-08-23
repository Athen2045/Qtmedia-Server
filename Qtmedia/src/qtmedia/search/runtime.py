"""Search cache and reporting adapters for CLI and privacy-safe bot callers."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .engine import SearchCandidate, VideoResult


class SearchCache(Protocol):
    """Cache interface shared by persistent CLI and ephemeral bot adapters."""

    def load_candidates(self, cache_key: str) -> list[SearchCandidate] | None:
        """Return fresh candidates or None for a cache miss."""

    def save_candidates(
        self, cache_key: str, candidates: list[SearchCandidate]
    ) -> None:
        """Store candidates under the caller-provided cache key."""

    def load_result(self, cache_key: str) -> VideoResult | None:
        """Return a fresh inspected result or None for a miss."""

    def save_result(self, cache_key: str, result: VideoResult) -> None:
        """Store an inspected result under the caller-provided key."""


@dataclass(frozen=True)
class SearchEvent:
    """A privacy-safe search event containing no query or source value."""

    stage: str
    site: str | None = None
    count: int | None = None
    code: str | None = None


@dataclass(frozen=True)
class SearchRuntime:
    """Caller-selected search persistence and event policy."""

    cache: SearchCache
    emit: Callable[[SearchEvent], None]
    display: Callable[[str], None] = print

    def report(self, event: SearchEvent) -> None:
        """Forward one value-free event to the caller-selected adapter."""
        self.emit(event)

    def show(self, message: str) -> None:
        """Forward caller-facing text to the selected presentation adapter."""
        self.display(message)


@dataclass(frozen=True, slots=True)
class _MemoryEntry:
    created_at: float
    value: object


class EphemeralSearchCache:
    """Bounded, process-local search cache for privacy-sensitive callers."""

    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_entries: int,
        clock: Callable[[], float] = time.time,
    ):
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[tuple[str, str], _MemoryEntry] = OrderedDict()
        self._lock = threading.Lock()

    def _prune_locked(self, now: float) -> None:
        expired = [
            key
            for key, entry in self._entries.items()
            if now - entry.created_at >= self._ttl_seconds
        ]
        for key in expired:
            self._entries.pop(key, None)

    def _load(self, kind: str, cache_key: str):
        with self._lock:
            self._prune_locked(self._clock())
            entry = self._entries.get((kind, cache_key))
            return None if entry is None else entry.value

    def _save(self, kind: str, cache_key: str, value: object) -> None:
        with self._lock:
            now = self._clock()
            self._prune_locked(now)
            key = (kind, cache_key)
            self._entries.pop(key, None)
            while len(self._entries) >= self._max_entries:
                self._entries.popitem(last=False)
            self._entries[key] = _MemoryEntry(now, value)

    def load_candidates(self, cache_key: str) -> list[SearchCandidate] | None:
        """Return a copied list of fresh in-memory candidates."""
        candidates = self._load("candidates", cache_key)
        return None if candidates is None else list(candidates)

    def save_candidates(
        self, cache_key: str, candidates: list[SearchCandidate]
    ) -> None:
        """Store candidates in bounded process memory only."""
        self._save("candidates", cache_key, tuple(candidates))

    def load_result(self, cache_key: str) -> VideoResult | None:
        """Return a fresh inspected result from process memory."""
        return self._load("result", cache_key)

    def save_result(self, cache_key: str, result: VideoResult) -> None:
        """Store an inspected result in bounded process memory only."""
        self._save("result", cache_key, result)


class SqliteSearchCache:
    """Persistent SQLite search cache preserving the existing CLI behavior."""

    def __init__(
        self,
        database_path: Path,
        *,
        result_ttl_seconds: float,
        candidate_ttl_seconds: float,
        clock: Callable[[], float] = time.time,
    ):
        if result_ttl_seconds <= 0 or candidate_ttl_seconds <= 0:
            raise ValueError("cache TTLs must be positive")
        self._database_path = database_path
        self._result_ttl_seconds = result_ttl_seconds
        self._candidate_ttl_seconds = candidate_ttl_seconds
        self._clock = clock
        self._initialized = False
        self._initialization_lock = threading.Lock()

    def _initialize(self) -> None:
        with self._initialization_lock:
            if self._initialized:
                return
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self._database_path, timeout=30) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS inspected_videos (
                        url TEXT PRIMARY KEY,
                        checked_at REAL NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS search_pages (
                        cache_key TEXT PRIMARY KEY,
                        checked_at REAL NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
            self._initialized = True

    def load_candidates(self, cache_key: str) -> list[SearchCandidate] | None:
        """Load a fresh candidate list from SQLite."""
        self._initialize()
        cutoff = self._clock() - self._candidate_ttl_seconds
        with sqlite3.connect(self._database_path, timeout=30) as connection:
            row = connection.execute(
                "SELECT checked_at, payload FROM search_pages WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if not row or row[0] < cutoff:
            return None
        from .engine import SearchCandidate  # pylint: disable=import-outside-toplevel

        return [SearchCandidate(**item) for item in json.loads(row[1])]

    def save_candidates(
        self, cache_key: str, candidates: list[SearchCandidate]
    ) -> None:
        """Upsert a candidate list using parameterized SQLite values."""
        self._initialize()
        payload = json.dumps(
            [
                {"site": item.site, "title": item.title, "url": item.url}
                for item in candidates
            ]
        )
        with sqlite3.connect(self._database_path, timeout=30) as connection:
            connection.execute(
                """
                INSERT INTO search_pages(cache_key, checked_at, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    checked_at = excluded.checked_at,
                    payload = excluded.payload
                """,
                (cache_key, self._clock(), payload),
            )

    def load_result(self, cache_key: str) -> VideoResult | None:
        """Load a fresh inspected result from SQLite."""
        self._initialize()
        cutoff = self._clock() - self._result_ttl_seconds
        with sqlite3.connect(self._database_path, timeout=30) as connection:
            row = connection.execute(
                "SELECT checked_at, payload FROM inspected_videos WHERE url = ?",
                (cache_key,),
            ).fetchone()
        if not row or row[0] < cutoff:
            return None
        payload = json.loads(row[1])
        if "thumbnail_url" not in payload:
            return None
        from .engine import VideoResult  # pylint: disable=import-outside-toplevel

        return VideoResult(**payload)

    def save_result(self, cache_key: str, result: VideoResult) -> None:
        """Upsert an inspected result using parameterized SQLite values."""
        self._initialize()
        payload = json.dumps(
            {
                "title": result.title,
                "url": result.url,
                "site": result.site,
                "view_count": result.view_count,
                "max_height": result.max_height,
                "max_tbr": result.max_tbr,
                "thumbnail_url": result.thumbnail_url,
            }
        )
        with sqlite3.connect(self._database_path, timeout=30) as connection:
            connection.execute(
                """
                INSERT INTO inspected_videos(url, checked_at, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    checked_at = excluded.checked_at,
                    payload = excluded.payload
                """,
                (cache_key, self._clock(), payload),
            )
