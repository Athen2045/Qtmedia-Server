"""Interactive multi-site video search and download CLI.

This is an experimental companion to main.py. It searches result pages with
site adapters, then lets yt-dlp inspect and download only direct video URLs.
"""

from __future__ import annotations

import importlib.util
import json
import re
import signal
import sqlite3
import time
from concurrent.futures import (  # pylint: disable=no-name-in-module
    ThreadPoolExecutor,
    as_completed,
)
from dataclasses import dataclass
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .config import DOWNLOAD_ROOT, SEARCH_CACHE, ensure_runtime_directories
from .pmvhaven import fetch_metadata, is_pmvhaven_url

ensure_runtime_directories()
OUTPUT_FOLDER = DOWNLOAD_ROOT
# Searches should return the site's results by default. Optional filters can
# still be added from the Filters and Exclude menus.
MIN_VIEWS = 0
DEFAULT_FILTERS: list[str] = []
DEFAULT_EXCLUDES = ["ai", "ai-generated", "vr"]
REQUEST_TIMEOUT = 20
MAX_CANDIDATES_PER_SITE = 20
SEARCH_WORKERS = 8
INSPECTION_WORKERS = 4
CACHE_TTL_SECONDS = 24 * 60 * 60
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36"


# ANSI colors are supported by macOS Terminal and most modern terminals.
RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"


@dataclass(frozen=True)
class SiteAdapter:
    name: str
    search_url: str | None
    video_pattern: str
    disabled_reason: str | None = None
    fallback_search_urls: tuple[str, ...] = ()
    query_style: str = "plus"

    def make_search_urls(self, query: str) -> tuple[str, ...]:
        if self.search_url is None:
            raise ValueError(self.disabled_reason or "Search adapter is unavailable")
        if self.query_style == "slug":
            query_value = re.sub(r"[^a-z0-9]+", "-", query.casefold()).strip("-")
        else:
            query_value = quote_plus(query)
        templates = (self.search_url, *self.fallback_search_urls)
        return tuple(template.format(query=query_value) for template in templates)


def site_name_for_url(url: str) -> str:
    """Return a readable configured site name for a direct URL."""
    if is_pmvhaven_url(url):
        return "PMVHaven"
    host = urlparse(url).netloc.casefold().removeprefix("www.")
    for adapter in ADAPTERS:
        configured_host = urlparse(adapter.search_url or "").netloc.casefold().removeprefix("www.")
        if configured_host and (host == configured_host or host.endswith(f".{configured_host}")):
            return adapter.name
    return host or "Direct URL"


@dataclass
class VideoResult:
    title: str
    url: str
    site: str
    view_count: int | None
    max_height: int
    max_tbr: float

    @property
    def quality_score(self) -> tuple[int, float]:
        return self.max_height, self.max_tbr


@dataclass(frozen=True)
class SearchCandidate:
    site: str
    title: str
    url: str


ADAPTERS = [
    SiteAdapter("XVideos", "https://www.xvideos.com/?k={query}", r"/video(?:\.|\d)"),
    SiteAdapter("XHamster", "https://xhamster.com/search/{query}", r"/videos/"),
    SiteAdapter("SpankBang", "https://spankbang.com/s/{query}/", r"/video/"),
    SiteAdapter(
        "TNAFlix",
        "https://www.tnaflix.com/search/{query}",
        r"/[^/]+/[^/]+/video\d+|/video\d+",
        fallback_search_urls=(
            "https://www.tnaflix.com/search?search={query}",
            "https://www.tnaflix.com/search.php?search={query}",
        ),
    ),
    SiteAdapter(
        "YouJizz",
        "https://www.youjizz.com/tags/{query}-1.html",
        r"/videos/",
        query_style="slug",
    ),
    SiteAdapter(
        "YouPorn",
        "https://www.youporn.com/porntags/{query}/",
        r"/watch/",
        fallback_search_urls=(
            "https://www.youporn.com/search/?query={query}",
        ),
        query_style="slug",
    ),
]


def ydl_options() -> dict:
    options = {
        "format": "bestvideo+bestaudio/best",
        "noplaylist": True,
        "merge_output_format": "mp4",
        "outtmpl": str(OUTPUT_FOLDER / "%(title)s [%(id)s].%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }
    if importlib.util.find_spec("curl_cffi"):
        options["extractor_args"] = {"generic": {"impersonate": [""]}}
    return options


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()


def parse_int(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"([\d,.]+)\s*([KMB])?", value.upper())
    if not match:
        return None
    number = float(match.group(1).replace(",", ""))
    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    return int(number * multiplier.get(match.group(2), 1))


def search_adapter(adapter: SiteAdapter, query: str) -> list[SearchCandidate]:
    """Fetch and cheaply filter one site's search page."""
    if adapter.search_url is None:
        print(f"[{adapter.name}] search unavailable: {adapter.disabled_reason}")
        return []
    last_error: Exception | None = None
    response = None
    search_url = ""
    try:
        with requests.Session() as session:
            for search_url in adapter.make_search_urls(query):
                try:
                    response = session.get(
                        search_url,
                        headers={"User-Agent": USER_AGENT},
                        timeout=REQUEST_TIMEOUT,
                    )
                    response.raise_for_status()
                    break
                except requests.RequestException as error:
                    last_error = error
                    response = None
    except requests.RequestException as error:
        last_error = error
    if response is None:
        print(f"[{adapter.name}] search failed: {last_error}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    candidates: list[SearchCandidate] = []
    seen_urls: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = urljoin(search_url, anchor["href"])
        path = urlparse(href).path
        title = anchor.get("title") or anchor.get_text(" ", strip=True)
        if (
            re.search(adapter.video_pattern, path)
            and href not in seen_urls
            and title
        ):
            seen_urls.add(href)
            candidates.append(SearchCandidate(adapter.name, title, href))
    return candidates[:MAX_CANDIDATES_PER_SITE]


def text_passes_filters(
    title: str,
    url: str,
    filters: list[str],
    excludes: list[str],
) -> bool:
    text = f"{title} {url}".casefold()
    # Search-page anchor text is often a duration, username, or thumbnail
    # label. Include filters are therefore applied after yt-dlp extracts the
    # canonical title; only exclusions are safe at this early stage.
    return not any(term.casefold() in text for term in excludes)


def init_cache() -> None:
    with sqlite3.connect(SEARCH_CACHE, timeout=30) as connection:
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


def load_cached_result(url: str) -> VideoResult | None:
    cutoff = time.time() - CACHE_TTL_SECONDS
    with sqlite3.connect(SEARCH_CACHE, timeout=30) as connection:
        row = connection.execute(
            "SELECT checked_at, payload FROM inspected_videos WHERE url = ?",
            (url,),
        ).fetchone()
    if not row or row[0] < cutoff:
        return None
    data = json.loads(row[1])
    return VideoResult(**data)


def cache_result(result: VideoResult, cache_key: str | None = None) -> None:
    with sqlite3.connect(SEARCH_CACHE, timeout=30) as connection:
        connection.execute(
            """
            INSERT INTO inspected_videos(url, checked_at, payload)
            VALUES (?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                checked_at = excluded.checked_at,
                payload = excluded.payload
            """,
            (
                cache_key or result.url,
                time.time(),
                json.dumps(
                    {
                        "title": result.title,
                        "url": result.url,
                        "site": result.site,
                        "view_count": result.view_count,
                        "max_height": result.max_height,
                        "max_tbr": result.max_tbr,
                    }
                ),
            ),
        )


def inspect_candidate(candidate: SearchCandidate) -> VideoResult | None:
    cached = load_cached_result(candidate.url)
    if cached:
        return cached

    import yt_dlp

    pmv_metadata = None
    if is_pmvhaven_url(candidate.url):
        try:
            pmv_metadata = fetch_metadata(candidate.url)
        except (requests.RequestException, TypeError, ValueError) as error:
            print(f"[PMVHaven] API metadata unavailable: {error}")

    try:
        with yt_dlp.YoutubeDL(ydl_options()) as ydl:
            info = ydl.extract_info(candidate.url, download=False)
    except yt_dlp.utils.DownloadError as error:
        if pmv_metadata:
            result = VideoResult(
                title=pmv_metadata.title,
                url=pmv_metadata.url,
                site="PMVHaven",
                view_count=None,
                max_height=0,
                max_tbr=0,
            )
            cache_result(result, candidate.url)
            return result
        print(f"[{candidate.site}] skipped {candidate.url}: {error}")
        return None

    formats = info.get("formats") or []
    heights = [int(item["height"]) for item in formats if item.get("height")]
    bitrates = [float(item["tbr"]) for item in formats if item.get("tbr")]
    result = VideoResult(
        title=info.get("title") or (pmv_metadata.title if pmv_metadata else None) or info.get("id") or candidate.url,
        url=info.get("webpage_url") or candidate.url,
        site=candidate.site,
        view_count=info.get("view_count"),
        max_height=max(heights, default=0),
        max_tbr=max(bitrates, default=0),
    )
    cache_result(result, candidate.url)
    return result


def passes_filters(
    result: VideoResult,
    filters: list[str],
    excludes: list[str],
    min_views: int,
    extra_text: str = "",
) -> bool:
    return filter_rejection_reason(result, filters, excludes, min_views, extra_text) is None


def filter_rejection_reason(
    result: VideoResult,
    filters: list[str],
    excludes: list[str],
    min_views: int,
    extra_text: str = "",
) -> str | None:
    """Return why a result was rejected, or None when it passes."""
    text = f"{extra_text} {result.title} {result.url}".casefold()
    if result.view_count is not None and result.view_count < min_views:
        return "minimum views"
    if any(term.casefold() in text for term in excludes):
        return "exclusion"
    if filters and not any(term.casefold() in text for term in filters):
        return "include filter"
    return None


def deduplicate(results: list[VideoResult]) -> list[VideoResult]:
    best: dict[str, VideoResult] = {}
    for result in results:
        key = normalize_title(result.title)
        if not key or key not in best or result.quality_score > best[key].quality_score:
            best[key] = result
    return sorted(best.values(), key=lambda item: (-item.max_height, item.title.casefold()))


def search(
    query: str,
    filters: list[str],
    excludes: list[str],
    min_views: int,
) -> list[VideoResult]:
    init_cache()
    candidates: list[SearchCandidate] = []
    with ThreadPoolExecutor(max_workers=min(SEARCH_WORKERS, len(ADAPTERS))) as pool:
        searches = [pool.submit(search_adapter, adapter, query) for adapter in ADAPTERS]
        for future in as_completed(searches):
            try:
                found_candidates = future.result()
            except Exception as error:  # noqa: BLE001 - isolate one failed worker
                print(f"Search worker failed: {error}")
                continue
            for candidate in found_candidates:
                if text_passes_filters(candidate.title, candidate.url, filters, excludes):
                    candidates.append(candidate)

    unique_candidates: dict[str, SearchCandidate] = {}
    for candidate in candidates:
        unique_candidates.setdefault(candidate.url, candidate)

    print(f"Found {len(unique_candidates)} candidate links before yt-dlp inspection.")

    results: list[VideoResult] = []
    extraction_failures = 0
    rejection_counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=INSPECTION_WORKERS) as pool:
        inspections = {
            pool.submit(inspect_candidate, candidate): candidate
            for candidate in unique_candidates.values()
        }
        for index, future in enumerate(as_completed(inspections), 1):
            candidate = inspections[future]
            print(f"Inspected {index}/{len(inspections)}: {candidate.title}")
            try:
                result = future.result()
            except Exception as error:  # noqa: BLE001 - isolate one failed worker
                print(f"[{candidate.site}] inspection failed: {error}")
                extraction_failures += 1
                continue
            if not result:
                extraction_failures += 1
                continue
            rejection_reason = filter_rejection_reason(
                result,
                filters,
                excludes,
                min_views,
                extra_text=candidate.title,
            )
            if rejection_reason is None:
                results.append(result)
                quality = f"{result.max_height}p" if result.max_height else "unknown quality"
                print(f"Match found: {result.title} ({quality})")
                print(f"Preview: {result.url}")
            else:
                rejection_counts[rejection_reason] = rejection_counts.get(rejection_reason, 0) + 1
    filtered_results = sum(rejection_counts.values())
    rejection_summary = ", ".join(
        f"{count} {reason}" for reason, count in sorted(rejection_counts.items())
    ) or "none"
    print(
        f"Inspection summary: {len(results)} matched, "
        f"{filtered_results} filtered ({rejection_summary}), "
        f"{extraction_failures} unavailable."
    )
    if not results and filtered_results:
        print("Active settings removed every inspected result:")
        print(f"  Include filters: {filters or '(none)'}")
        print(f"  Exclusions: {excludes or '(none)'}")
        print(f"  Minimum views: {min_views}")
    return deduplicate(results)


def inspect_direct_url(url: str) -> VideoResult | None:
    """Inspect a user-provided URL with yt-dlp without downloading it."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        print("Enter a complete http:// or https:// video URL.")
        return None

    result = inspect_candidate(SearchCandidate(site_name_for_url(url), url, url))
    if result:
        quality = f"{result.max_height}p" if result.max_height else "unknown quality"
        print(f"Title: {result.title}")
        print(f"Site: {result.site}")
        print(f"Best quality: {quality}")
        print(f"URL: {result.url}")
    return result


def print_results(results: list[VideoResult]) -> None:
    if not results:
        print("No matching videos found.")
        return
    for index, result in enumerate(results, 1):
        views = "unknown" if result.view_count is None else f"{result.view_count:,}"
        quality = f"{result.max_height}p" if result.max_height else "unknown quality"
        print(f"\n{index}. {result.title}")
        print(f"   Site: {result.site} | Views: {views} | Best: {quality}")
        print(f"   URL: {result.url}")


def print_menu(filters: list[str], excludes: list[str], min_views: int) -> None:
    """Render the application dashboard and menu using plain ASCII borders."""
    width = 72
    filter_text = ", ".join(filters) if filters else "(none)"
    print()
    print(f"{CYAN}+{'=' * width}+{RESET}")
    print(f"{CYAN}|{RESET}{BOLD}                         PRIVATE SEARCH                         {RESET}{CYAN}|{RESET}")
    print(f"{CYAN}+{'-' * width}+{RESET}")
    print(f"{CYAN}|{RESET} Applied parameters:                                                {CYAN}|{RESET}")
    print(f"{CYAN}|{RESET}   Include filters : {YELLOW}{filter_text[:52]:<52}{RESET} {CYAN}|{RESET}")
    print(f"{CYAN}|{RESET}   Minimum views   : {YELLOW}{min_views!s:<52}{RESET} {CYAN}|{RESET}")
    print(f"{CYAN}+{'-' * width}+{RESET}")
    print(f"{CYAN}|{RESET} {GREEN}1{RESET} Search titles       {GREEN}2{RESET} Include filters     {GREEN}3{RESET} Show last results   {CYAN}|{RESET}")
    print(f"{CYAN}|{RESET} {GREEN}4{RESET} Inspect direct URL  {GREEN}5{RESET} Download             {GREEN}6{RESET} Quit                 {CYAN}|{RESET}")
    print(f"{CYAN}+{'=' * width}+{RESET}")


def download_selected(results: list[VideoResult]) -> None:
    if not results:
        print("Search first, then choose a result to download.")
        return
    choice = input("Enter result number to download (or blank to cancel): ").strip()
    if not choice:
        return
    try:
        result = results[int(choice) - 1]
    except (ValueError, IndexError):
        print("Invalid result number.")
        return

    import yt_dlp

    OUTPUT_FOLDER.mkdir(exist_ok=True)
    print(f"Downloading: {result.title}")
    try:
        with yt_dlp.YoutubeDL(ydl_options()) as ydl:
            ydl.download([result.url])
    except yt_dlp.utils.DownloadError as error:
        print(f"Download failed: {error}")


def filter_menu(filters: list[str], min_views: int) -> int:
    while True:
        print(f"\nFilters: {filters or '[none]'} | Minimum views: {min_views}")
        print("1) Add filter  2) Remove filter  3) Set minimum views  4) Back")
        choice = input("> ").strip()
        if choice == "1":
            term = input("Add filter term: ").strip()
            if term and term.casefold() not in {item.casefold() for item in filters}:
                filters.append(term)
        elif choice == "2":
            term = input("Remove filter term: ").strip().casefold()
            filters[:] = [item for item in filters if item.casefold() != term]
        elif choice == "3":
            try:
                min_views = max(0, int(input("Minimum views: ").strip()))
            except ValueError:
                print("Enter a whole number.")
        elif choice == "4":
            return min_views
        else:
            print("Choose 1, 2, 3, or 4.")


def exclude_menu(excludes: list[str]) -> None:
    while True:
        print(f"\nExcluded terms: {excludes or '[none]'}")
        print("1) Add excluded term  2) Remove excluded term  3) Back")
        choice = input("> ").strip()
        if choice == "1":
            term = input("Exclude term/tag: ").strip()
            if term and term.casefold() not in {item.casefold() for item in excludes}:
                excludes.append(term)
        elif choice == "2":
            term = input("Remove excluded term: ").strip().casefold()
            excludes[:] = [item for item in excludes if item.casefold() != term]
        elif choice == "3":
            return
        else:
            print("Choose 1, 2, or 3.")


def run() -> None:
    filters = DEFAULT_FILTERS.copy()
    excludes = DEFAULT_EXCLUDES.copy()
    min_views = MIN_VIEWS
    results: list[VideoResult] = []

    while True:
        print_menu(filters, excludes, min_views)
        choice = input("> ").strip()
        if choice == "1":
            query = input("Search title: ").strip()
            if query:
                results = search(query, filters, excludes, min_views)
                print_results(results)
        elif choice == "2":
            min_views = filter_menu(filters, min_views)
        elif choice == "3":
            print_results(results)
        elif choice == "4":
            url = input("Video URL: ").strip()
            if url:
                direct_result = inspect_direct_url(url)
                if direct_result:
                    results = [direct_result]
        elif choice == "5":
            download_selected(results)
        elif choice == "6":
            print("Goodbye.")
            return
        else:
            print("Choose 1, 2, 3, 4, 5, or 6.")


def main() -> None:
    signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        run()
    except (KeyboardInterrupt, EOFError):
        print("\nStopped by user.")


if __name__ == "__main__":
    main()
