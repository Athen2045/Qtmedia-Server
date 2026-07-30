"""Optional adapter for a self-hosted Lustpress REST API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urljoin

import requests

LUSTPRESS_BASE_URL = os.getenv("LUSTPRESS_BASE_URL", "").strip().rstrip("/")
REQUEST_TIMEOUT = 20
SUPPORTED_SITES = ("xvideos", "xhamster", "youporn")


@dataclass(frozen=True)
class LustpressCandidate:
    site: str
    title: str
    url: str


def is_configured() -> bool:
    return bool(LUSTPRESS_BASE_URL)


def _records(payload: object) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if isinstance(data, dict):
        for key in ("videos", "results", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def search_site(site: str, query: str, page: int = 1) -> list[LustpressCandidate]:
    if not is_configured():
        return []
    if site not in SUPPORTED_SITES:
        raise ValueError(f"Unsupported Lustpress site: {site}")

    response = requests.get(
        urljoin(f"{LUSTPRESS_BASE_URL}/", f"{site}/search"),
        params={"key": query, "page": page},
        headers={"Accept": "application/json", "User-Agent": "private-search/0.1"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and payload.get("success") is False:
        return []

    candidates: list[LustpressCandidate] = []
    seen: set[str] = set()
    for item in _records(payload):
        url = item.get("link") or item.get("url") or item.get("webpage_url")
        title = item.get("title") or item.get("name")
        if isinstance(url, str) and isinstance(title, str) and url not in seen:
            seen.add(url)
            candidates.append(LustpressCandidate(site.title(), title.strip(), url))
    return candidates
