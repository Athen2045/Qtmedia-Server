"""Small, fail-closed provider adapter registry for bot inspection."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

from .eporner import EpornerAdapter
from .noodlemagazine import NoodleMagazineAdapter


@dataclass(frozen=True, slots=True)
class BotSourceAdapter:
    """Provider-specific page candidates and transfer ownership rules."""

    name: str
    page_hosts: frozenset[str]
    video_id: Callable[[str], str | None]
    alternate_urls: Callable[[str], tuple[str, ...]]
    impersonate: str | None = None

    def matches(self, url: str) -> bool:
        """Return whether the URL is a supported page for this provider."""

        parsed = urlsplit(url)
        host = (parsed.hostname or "").casefold().rstrip(".")
        return host in self.page_hosts and self.video_id(url) is not None

    def inspection_urls(self, url: str) -> tuple[str, ...]:
        """Return de-duplicated page variants in least-surprising order."""

        if not self.matches(url):
            return ()
        values: list[str] = []
        for candidate in (url, *self.alternate_urls(url)):
            if candidate not in values:
                values.append(candidate)
        return tuple(values)

    def owns_transfer_url(self, source_url: str, transfer_url: str) -> bool:
        """Allow only a same-provider, same-video alternate page URL."""

        if not self.matches(source_url) or not self.matches(transfer_url):
            return False
        return self.video_id(source_url) == self.video_id(transfer_url)


ADAPTERS: tuple[BotSourceAdapter, ...] = (
    BotSourceAdapter(
        name="eporner",
        page_hosts=frozenset({"eporner.com", "www.eporner.com"}),
        video_id=EpornerAdapter.video_id,
        alternate_urls=EpornerAdapter.alternate_urls,
    ),
    BotSourceAdapter(
        name="noodlemagazine",
        page_hosts=frozenset(
            {
                "noodlemagazine.com",
                "www.noodlemagazine.com",
                "adult.noodlemagazine.com",
            }
        ),
        video_id=NoodleMagazineAdapter.video_id,
        alternate_urls=NoodleMagazineAdapter.alternate_urls,
        impersonate="chrome131",
    ),
)


def adapter_for_url(url: str) -> BotSourceAdapter | None:
    """Return the narrow adapter that owns one supported provider page."""

    return next((adapter for adapter in ADAPTERS if adapter.matches(url)), None)


def inspection_candidates(url: str, resolved_url: str) -> Iterable[tuple[str, bool]]:
    """Yield normal then generic-extractor candidates without duplicates."""

    adapter = adapter_for_url(url)
    page_urls = adapter.inspection_urls(url) if adapter else (resolved_url,)
    values = list(page_urls)
    if resolved_url not in values:
        values.insert(0, resolved_url)
    seen: set[tuple[str, bool]] = set()
    for force_generic in (False, True):
        for candidate in values:
            attempt = (candidate, force_generic)
            if attempt not in seen:
                seen.add(attempt)
                yield attempt
