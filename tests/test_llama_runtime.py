from __future__ import annotations

from pathlib import Path

import pytest

from private_search.ai import runtime
from private_search.ai.runtime import (
    LlamaServer,
    RuntimeConfigurationError,
    RuntimeSettings,
)


class FakeProcess:
    def __init__(self) -> None:
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.returncode = 0

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    def wait(self, timeout=None) -> int:
        self.wait_calls += 1
        return self.returncode or 0


def valid_settings(tmp_path: Path, *, startup_timeout: float = 1.0) -> RuntimeSettings:
    executable = tmp_path / "llama-server.exe"
    model = tmp_path / "model.gguf"
    mmproj = tmp_path / "mmproj.gguf"
    for path in (executable, model, mmproj):
        path.write_bytes(b"artifact")
    return RuntimeSettings(
        executable=executable,
        model=model,
        mmproj=mmproj,
        host="127.0.0.1",
        port=8080,
        context_size=4096,
        n_predict=128,
        device="CUDA0",
        gpu_layers=999,
        startup_timeout=startup_timeout,
        poll_interval=0.001,
        shutdown_timeout=0.1,
    )


def test_runtime_settings_defaults_to_downloaded_local_artifacts():
    settings = RuntimeSettings.from_environment()

    assert settings.host == "127.0.0.1"
    assert settings.port == 8080
    assert settings.context_size == 8192
    assert settings.n_predict == 4096
    assert settings.batch_size == 2048
    assert settings.ubatch_size == 512
    assert settings.flash_attn == "on"
    assert settings.model.name.endswith("Q4_K_M.gguf")
    assert settings.mmproj is not None
    assert settings.mmproj.name.startswith("mmproj-")


def test_runtime_settings_rejects_non_loopback_host(tmp_path: Path):
    settings = valid_settings(tmp_path)
    settings = settings.__class__(**{**settings.__dict__, "host": "0.0.0.0"})

    with pytest.raises(RuntimeConfigurationError, match="loopback"):
        settings.validate()


def test_build_command_uses_model_projector_and_loopback(tmp_path: Path):
    settings = valid_settings(tmp_path)

    command = LlamaServer(settings).build_command()

    assert command[0] == str(settings.executable)
    assert "--model" in command
    assert str(settings.model) in command
    assert "--mmproj" in command
    assert str(settings.mmproj) in command
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert "--no-webui" in command
    assert command[command.index("--batch-size") + 1] == "2048"
    assert command[command.index("--ubatch-size") + 1] == "512"
    assert command[command.index("--flash-attn") + 1] == settings.flash_attn
    assert "--parallel" in command
    assert command[command.index("--device") + 1] == "CUDA0"
    assert command[command.index("--gpu-layers") + 1] == "999"


def test_server_exposes_http_endpoints(tmp_path: Path):
    settings = valid_settings(tmp_path)

    server = LlamaServer(settings)

    assert server.server_url == "http://127.0.0.1:8080"
    assert server.health_url == "http://127.0.0.1:8080/health"


def test_start_waits_for_health_and_stop_terminates_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    process = FakeProcess()
    health = iter([False, True])
    monkeypatch.setattr(runtime, "_healthcheck", lambda url, timeout: next(health))
    server = LlamaServer(
        valid_settings(tmp_path),
        popen_factory=lambda *args, **kwargs: process,
    )

    server.start()

    assert server.is_running
    server.stop()
    assert process.terminate_calls == 1


def test_start_failure_cleans_up_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    process = FakeProcess()
    monkeypatch.setattr(runtime, "_healthcheck", lambda url, timeout: False)
    settings = valid_settings(tmp_path, startup_timeout=0.01)
    server = LlamaServer(
        settings,
        popen_factory=lambda *args, **kwargs: process,
    )

    with pytest.raises(RuntimeError, match="ready"):
        server.start()

    assert process.terminate_calls == 1
