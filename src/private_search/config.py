"""Runtime paths and application defaults."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = PROJECT_ROOT / "var"
DOWNLOAD_ROOT = RUNTIME_ROOT / "downloads"
CACHE_ROOT = RUNTIME_ROOT / "cache"
SEARCH_CACHE = CACHE_ROOT / "search.sqlite3"
FACE_INDEX_PATH = RUNTIME_ROOT / "face-index.sqlite"
FACE_CROP_ROOT = RUNTIME_ROOT / "face-crops"
IMAGE_ROOT = RUNTIME_ROOT / "images"
MODEL_ROOT = RUNTIME_ROOT / "models" / "qwen3.5-4b-uncensored"
LLAMA_RUNTIME_ROOT = RUNTIME_ROOT / "runtime" / "llama.cpp"
BLACKBIRD_ROOT = RUNTIME_ROOT / "tools" / "blackbird"
BLACKBIRD_WORKER_PATH = PROJECT_ROOT / "src" / "private_search" / "osint" / "blackbird_worker.py"
INSIGHTFACE_ROOT = RUNTIME_ROOT / "tools" / "insightface"


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


class ConfigurationError(ValueError):
    """Raised when environment configuration is invalid."""


def runtime_directories() -> tuple[Path, ...]:
    """Directories the application manages under the local runtime root."""

    return (
        RUNTIME_ROOT,
        DOWNLOAD_ROOT,
        CACHE_ROOT,
        IMAGE_ROOT,
        FACE_INDEX_PATH.parent,
        FACE_CROP_ROOT,
    )


def ensure_runtime_directories() -> None:
    for directory in runtime_directories():
        directory.mkdir(parents=True, exist_ok=True)


def _environment(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def _env_text(env: Mapping[str, str], name: str) -> str:
    return env.get(name, "").strip()


def _env_path(env: Mapping[str, str], name: str, default: Path) -> Path:
    configured = _env_text(env, name)
    if configured:
        return Path(configured).expanduser()
    return default


def _env_int(
    env: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    label: str,
) -> int:
    raw = _env_text(env, name)
    if not raw:
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise ConfigurationError(f"{name} must be an integer value") from exc
    if value < minimum:
        raise ConfigurationError(f"{label} must be at least {minimum} second" if minimum == 1 and "timeout" in label.lower() else f"{label} must be at least {minimum}")
    return value


def _env_bool(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    raw = _env_text(env, name)
    if not raw:
        return default
    normalized = raw.casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean value")


def _validated_provider_policy(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized:
        return "cuda_or_cpu"
    if normalized not in {"cpu", "cuda", "cuda_or_cpu"}:
        raise ConfigurationError(
            "InsightFace provider policy must be one of: cpu, cuda, cuda_or_cpu"
        )
    return normalized


@dataclass(frozen=True)
class BlackbirdRuntimeSettings:
    """Typed Blackbird worker settings sourced from environment variables."""

    root: Path = BLACKBIRD_ROOT
    python: Path = BLACKBIRD_ROOT / ".venv" / "Scripts" / "python.exe"
    timeout_seconds: int = 300
    request_timeout_seconds: int = 15
    threads: int = 8
    update_sites: bool = False

    @classmethod
    def from_environment(
        cls, env: Mapping[str, str] | None = None
    ) -> BlackbirdRuntimeSettings:
        environment = _environment(env)
        root = _env_path(environment, "PRIVATE_SEARCH_BLACKBIRD_ROOT", BLACKBIRD_ROOT)
        timeout_seconds = _env_int(
            environment,
            "PRIVATE_SEARCH_BLACKBIRD_TIMEOUT",
            300,
            minimum=1,
            label="Blackbird timeout",
        )
        request_timeout_seconds = _env_int(
            environment,
            "PRIVATE_SEARCH_BLACKBIRD_REQUEST_TIMEOUT",
            15,
            minimum=1,
            label="Blackbird request timeout",
        )
        threads = _env_int(
            environment,
            "PRIVATE_SEARCH_BLACKBIRD_THREADS",
            8,
            minimum=1,
            label="Blackbird thread count",
        )
        return cls(
            root=root,
            python=_env_path(
                environment,
                "PRIVATE_SEARCH_BLACKBIRD_PYTHON",
                root / ".venv" / "Scripts" / "python.exe",
            ),
            timeout_seconds=timeout_seconds,
            request_timeout_seconds=request_timeout_seconds,
            threads=threads,
            update_sites=_env_bool(
                environment,
                "PRIVATE_SEARCH_BLACKBIRD_UPDATE_SITES",
                default=False,
            ),
        )


@dataclass(frozen=True)
class InsightFaceRuntimeSettings:
    """Typed InsightFace worker settings sourced from environment variables."""

    root: Path = INSIGHTFACE_ROOT
    python: Path = INSIGHTFACE_ROOT / ".venv" / "Scripts" / "python.exe"
    model_name: str = "buffalo_l"
    image_root: Path = IMAGE_ROOT
    index_path: Path = FACE_INDEX_PATH
    crop_root: Path = FACE_CROP_ROOT
    timeout_seconds: int = 300
    provider_policy: str = "cuda_or_cpu"
    keep_crops: bool = False

    @classmethod
    def from_environment(
        cls, env: Mapping[str, str] | None = None
    ) -> InsightFaceRuntimeSettings:
        environment = _environment(env)
        root = _env_path(environment, "PRIVATE_SEARCH_INSIGHTFACE_ROOT", INSIGHTFACE_ROOT)
        model_name = _env_text(environment, "PRIVATE_SEARCH_INSIGHTFACE_MODEL") or "buffalo_l"
        return cls(
            root=root,
            python=_env_path(
                environment,
                "PRIVATE_SEARCH_INSIGHTFACE_PYTHON",
                root / ".venv" / "Scripts" / "python.exe",
            ),
            model_name=model_name,
            image_root=_env_path(environment, "PRIVATE_SEARCH_INSIGHTFACE_IMAGE_ROOT", IMAGE_ROOT),
            index_path=_env_path(
                environment,
                "PRIVATE_SEARCH_INSIGHTFACE_INDEX_PATH",
                FACE_INDEX_PATH,
            ),
            crop_root=_env_path(
                environment,
                "PRIVATE_SEARCH_INSIGHTFACE_CROP_ROOT",
                FACE_CROP_ROOT,
            ),
            timeout_seconds=_env_int(
                environment,
                "PRIVATE_SEARCH_INSIGHTFACE_TIMEOUT",
                300,
                minimum=1,
                label="InsightFace timeout",
            ),
            provider_policy=_validated_provider_policy(
                _env_text(environment, "PRIVATE_SEARCH_INSIGHTFACE_PROVIDER_POLICY")
                or "cuda_or_cpu"
            ),
            keep_crops=_env_bool(
                environment,
                "PRIVATE_SEARCH_INSIGHTFACE_KEEP_CROPS",
                default=False,
            ),
        )
