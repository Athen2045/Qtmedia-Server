"""Runtime paths and application defaults."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = PROJECT_ROOT / "var"
DOWNLOAD_ROOT = RUNTIME_ROOT / "downloads"
CACHE_ROOT = RUNTIME_ROOT / "cache"
SEARCH_CACHE = CACHE_ROOT / "search.sqlite3"
FACE_INDEX_PATH = RUNTIME_ROOT / "face-index.sqlite"
FACE_CROP_ROOT = RUNTIME_ROOT / "face-crops"
MODEL_ROOT = RUNTIME_ROOT / "models" / "qwen3.5-4b-uncensored"
LLAMA_RUNTIME_ROOT = RUNTIME_ROOT / "runtime" / "llama.cpp"


def _preferred_path(*candidates: Path) -> Path:
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


LLAMA_MODEL = MODEL_ROOT / "Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf"
LLAMA_MMPROJ = MODEL_ROOT / "mmproj-Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-BF16.gguf"
LLAMA_SERVER_EXECUTABLE = _preferred_path(
    LLAMA_RUNTIME_ROOT / "b10451-cuda13" / "llama-server.exe",
    LLAMA_RUNTIME_ROOT / "b10451" / "bin" / "llama-server.exe",
)


def ensure_runtime_directories() -> None:
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    FACE_CROP_ROOT.mkdir(parents=True, exist_ok=True)
