"""Runtime paths and application defaults."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = PROJECT_ROOT / "var"
DOWNLOAD_ROOT = RUNTIME_ROOT / "downloads"
CACHE_ROOT = RUNTIME_ROOT / "cache"
SEARCH_CACHE = CACHE_ROOT / "search.sqlite3"
MODEL_ROOT = RUNTIME_ROOT / "models" / "qwen3.5-4b-uncensored"
CPU_RUNTIME_ROOT = RUNTIME_ROOT / "runtime" / "llama.cpp" / "b10451" / "bin"
CUDA_RUNTIME_ROOT = RUNTIME_ROOT / "runtime" / "llama.cpp" / "b10451-cuda13"
AI_RUNTIME_ROOT = (
    CUDA_RUNTIME_ROOT if (CUDA_RUNTIME_ROOT / "llama-server.exe").is_file() else CPU_RUNTIME_ROOT
)
LLAMA_SERVER_EXECUTABLE = AI_RUNTIME_ROOT / "llama-server.exe"
LLAMA_MODEL = MODEL_ROOT / "Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf"
LLAMA_MMPROJ = MODEL_ROOT / "mmproj-Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-BF16.gguf"
BLACKBIRD_ROOT = PROJECT_ROOT / "Update" / "blackbird"
INSIGHTFACE_ROOT = PROJECT_ROOT / "Update" / "insightface"
BLACKBIRD_TIMEOUT_SECONDS = 300
INSIGHTFACE_TIMEOUT_SECONDS = 300
CONFIDENCE_THRESHOLD = 75.0
FACE_INDEX_PATH = RUNTIME_ROOT / "face-index.sqlite"
FACE_CROP_ROOT = RUNTIME_ROOT / "face-crops"


def ensure_runtime_directories() -> None:
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    FACE_CROP_ROOT.mkdir(parents=True, exist_ok=True)
