"""Runtime paths and application defaults."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = PROJECT_ROOT / "var"
DOWNLOAD_ROOT = RUNTIME_ROOT / "downloads"
CACHE_ROOT = RUNTIME_ROOT / "cache"
SEARCH_CACHE = CACHE_ROOT / "search.sqlite3"


def ensure_runtime_directories() -> None:
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
