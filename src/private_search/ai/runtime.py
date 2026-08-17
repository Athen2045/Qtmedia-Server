"""Configuration and lifecycle management for a local llama.cpp server."""

from __future__ import annotations

import os
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from .. import config


class RuntimeConfigurationError(ValueError):
    """Raised when the local model runtime configuration is unsafe or invalid."""


class LlamaServerError(RuntimeError):
    """Raised when llama.cpp cannot be started or become ready."""


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as error:
        raise RuntimeConfigurationError(f"{name} must be an integer") from error


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError as error:
        raise RuntimeConfigurationError(f"{name} must be a number") from error


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser() if value and value.strip() else default


def _env_choice(name: str, default: str, choices: set[str]) -> str:
    value = os.getenv(name)
    choice = value.strip().casefold() if value and value.strip() else default
    if choice not in choices:
        allowed = ", ".join(sorted(choices))
        raise RuntimeConfigurationError(f"{name} must be one of: {allowed}")
    return choice


@dataclass(frozen=True)
class RuntimeSettings:
    """Validated settings needed to launch the local model server."""

    executable: Path
    model: Path
    mmproj: Path | None
    host: str = "127.0.0.1"
    port: int = 8080
    context_size: int = 8192
    n_predict: int = 4096
    batch_size: int = 2048
    ubatch_size: int = 512
    flash_attn: str = "auto"
    device: str | None = None
    gpu_layers: int = 999
    startup_timeout: float = 60.0
    poll_interval: float = 0.25
    shutdown_timeout: float = 5.0

    @classmethod
    def from_environment(cls) -> RuntimeSettings:
        """Resolve settings from environment overrides and project-local defaults."""

        mmproj_value = os.getenv("PRIVATE_SEARCH_LLM_MMPROJ")
        if mmproj_value is not None and mmproj_value.strip().casefold() in {"", "none", "off"}:
            mmproj: Path | None = None
        else:
            mmproj = _env_path("PRIVATE_SEARCH_LLM_MMPROJ", config.LLAMA_MMPROJ)

        executable = _env_path("PRIVATE_SEARCH_LLM_SERVER", config.LLAMA_SERVER_EXECUTABLE)
        device_value = os.getenv("PRIVATE_SEARCH_LLM_DEVICE")
        if device_value is not None and not device_value.strip():
            device: str | None = None
        elif device_value is not None:
            device = device_value.strip()
        else:
            device = "CUDA0" if "cuda" in str(executable.parent).casefold() else None

        flash_default = "on" if device else "auto"

        return cls(
            executable=executable,
            model=_env_path("PRIVATE_SEARCH_LLM_MODEL", config.LLAMA_MODEL),
            mmproj=mmproj,
            host=os.getenv("PRIVATE_SEARCH_LLM_HOST", "127.0.0.1").strip(),
            port=_env_int("PRIVATE_SEARCH_LLM_PORT", 8080),
            context_size=_env_int("PRIVATE_SEARCH_LLM_CONTEXT", 8192),
            n_predict=_env_int("PRIVATE_SEARCH_LLM_N_PREDICT", 4096),
            batch_size=_env_int("PRIVATE_SEARCH_LLM_BATCH", 2048),
            ubatch_size=_env_int("PRIVATE_SEARCH_LLM_UBATCH", 512),
            flash_attn=_env_choice(
                "PRIVATE_SEARCH_LLM_FLASH_ATTN",
                flash_default,
                {"on", "off", "auto"},
            ),
            device=device,
            gpu_layers=_env_int("PRIVATE_SEARCH_LLM_GPU_LAYERS", 999),
            startup_timeout=_env_float("PRIVATE_SEARCH_LLM_STARTUP_TIMEOUT", 60.0),
            poll_interval=_env_float("PRIVATE_SEARCH_LLM_POLL_INTERVAL", 0.25),
            shutdown_timeout=_env_float("PRIVATE_SEARCH_LLM_SHUTDOWN_TIMEOUT", 5.0),
        )

    @property
    def server_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def health_url(self) -> str:
        return f"{self.server_url}/health"

    def validate(self) -> None:
        if self.host not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeConfigurationError("llama.cpp must bind to a loopback host")
        if not 1 <= self.port <= 65535:
            raise RuntimeConfigurationError("llama.cpp port must be between 1 and 65535")
        if self.context_size < 1:
            raise RuntimeConfigurationError("llama.cpp context size must be positive")
        if self.n_predict < 1:
            raise RuntimeConfigurationError("llama.cpp prediction limit must be positive")
        if self.batch_size < 1:
            raise RuntimeConfigurationError("llama.cpp batch size must be positive")
        if self.ubatch_size < 1:
            raise RuntimeConfigurationError("llama.cpp physical batch size must be positive")
        if self.ubatch_size > self.batch_size:
            raise RuntimeConfigurationError(
                "llama.cpp physical batch size cannot exceed logical batch size"
            )
        if self.flash_attn not in {"on", "off", "auto"}:
            raise RuntimeConfigurationError(
                "llama.cpp Flash Attention must be on, off, or auto"
            )
        if self.gpu_layers < 0:
            raise RuntimeConfigurationError("llama.cpp GPU layer count cannot be negative")
        if self.startup_timeout <= 0:
            raise RuntimeConfigurationError("llama.cpp startup timeout must be positive")
        if self.poll_interval <= 0:
            raise RuntimeConfigurationError("llama.cpp poll interval must be positive")
        if self.shutdown_timeout <= 0:
            raise RuntimeConfigurationError("llama.cpp shutdown timeout must be positive")
        for label, path in (("llama-server executable", self.executable), ("model", self.model)):
            if not path.is_file():
                raise RuntimeConfigurationError(f"{label} was not found: {path}")
        if self.mmproj is not None and not self.mmproj.is_file():
            raise RuntimeConfigurationError(f"vision projector was not found: {self.mmproj}")


def _healthcheck(url: str, timeout: float) -> bool:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


class LlamaServer:
    """Own one llama.cpp child process and its readiness lifecycle."""

    def __init__(
        self,
        settings: RuntimeSettings,
        *,
        opener: Callable[[str, float], bool] | None = None,
        popen_factory: Callable[..., subprocess.Popen] | None = None,
    ) -> None:
        self.settings = settings
        self._healthcheck = opener or _healthcheck
        self._popen_factory = popen_factory or subprocess.Popen
        self._process: subprocess.Popen | None = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def server_url(self) -> str:
        return self.settings.server_url

    @property
    def health_url(self) -> str:
        return self.settings.health_url

    def build_command(self) -> list[str]:
        self.settings.validate()
        command = [
            str(self.settings.executable),
            "--model",
            str(self.settings.model),
            "--host",
            self.settings.host,
            "--port",
            str(self.settings.port),
            "--ctx-size",
            str(self.settings.context_size),
            "--n-predict",
            str(self.settings.n_predict),
            "--batch-size",
            str(self.settings.batch_size),
            "--ubatch-size",
            str(self.settings.ubatch_size),
            "--flash-attn",
            self.settings.flash_attn,
            "--parallel",
            "1",
            "--no-webui",
        ]
        if self.settings.device:
            command.extend(["--device", self.settings.device])
            command.extend(["--gpu-layers", str(self.settings.gpu_layers)])
        if self.settings.mmproj is not None:
            command.extend(
                [
                    "--mmproj",
                    str(self.settings.mmproj),
                    "--image-min-tokens",
                    "1024",
                ]
            )
        return command

    def start(self) -> None:
        if self.is_running:
            return
        command = self.build_command()
        try:
            self._process = self._popen_factory(
                command,
                cwd=str(self.settings.executable.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
        except OSError as error:
            raise LlamaServerError(f"could not start llama.cpp: {error}") from error

        deadline = time.monotonic() + self.settings.startup_timeout
        try:
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    raise LlamaServerError("llama.cpp exited before becoming ready")
                remaining = max(0.1, deadline - time.monotonic())
                if self._healthcheck(self.settings.health_url, min(1.0, remaining)):
                    return
                time.sleep(min(self.settings.poll_interval, remaining))
            raise LlamaServerError("llama.cpp did not become ready before the startup timeout")
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=self.settings.shutdown_timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.stop()
