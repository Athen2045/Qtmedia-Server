from __future__ import annotations

from pathlib import Path

import pytest

from private_search.ai.actions import AgentAction
from private_search.osint.smartimage import (
    SmartImageAdapter,
    SmartImageExecutionError,
    SmartImageSettings,
)


def test_smartimage_defaults_to_tmpfiles(monkeypatch):
    monkeypatch.delenv("PRIVATE_SEARCH_SMARTIMAGE_UPLOAD_ENGINE", raising=False)

    settings = SmartImageSettings.from_environment()

    assert settings.upload_engine == "TmpFiles"


def reverse_image_action(path: str) -> AgentAction:
    return AgentAction(
        action="reverse_image_search",
        reason="The user requested a reverse image search.",
        image_path=path,
    )


def test_smartimage_rdx_search_command_has_headless_execution_path():
    source = Path(
        "Update/SmartImage-4/SmartImage.Rdx/Commands/Search/SearchCommand.cs"
    ).read_text(encoding="utf-8")

    assert "UseHeadlessExecution" in source
    assert "!CommandSettings.Interactive" in source
    assert "Console.IsOutputRedirected" in source
    assert "Console.IsErrorRedirected" in source
    assert "await InitQueryAsync();" in source
    assert "await RunSearchAsync(null, m_ctsRunSearch.Token);" in source


def test_smartimage_headless_rows_do_not_cast_lists_to_arrays():
    source = Path(
        "Update/SmartImage-4/SmartImage.Rdx/Commands/Search/SearchCommand.cs"
    ).read_text(encoding="utf-8")

    assert "var row = list.ToArray();" in source
    assert "var row = (IRenderable[]) list;" not in source


def test_smartimage_adapter_runs_non_interactive_delimited_search(
    monkeypatch, tmp_path: Path
):
    executable = tmp_path / "SmartImage.exe"
    executable.write_bytes(b"fixture")
    image = tmp_path / "sample.jpg"
    image.write_bytes(b"image")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        output = Path(command[command.index("--output-file") + 1])
        output.write_text(
            "Name|Url|Similarity|Artist|Site\n"
            "Google #1|https://example.test/result|0.91|Artist|Google\n",
            encoding="utf-8",
        )
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("private_search.osint.smartimage.subprocess.run", fake_run)
    adapter = SmartImageAdapter(
        SmartImageSettings(executable=executable, timeout_seconds=9)
    )

    results = adapter(reverse_image_action(str(image)))

    assert results == [
        {
            "name": "Google #1",
            "url": "https://example.test/result",
            "similarity": "0.91",
            "artist": "Artist",
            "site": "Google",
        }
    ]
    command, kwargs = calls[0]
    assert command[:2] == [str(executable), str(image.resolve())]
    assert command[command.index("--interactive") + 1] == "false"
    assert command[command.index("--output-format") + 1] == "Delimited"
    assert command[command.index("--output-delim") + 1] == "|"
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 9
    assert kwargs["env"]["NOVUS_DATA_FOLDER"]


def test_smartimage_adapter_rejects_missing_image_before_process(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        "private_search.osint.smartimage.subprocess.run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    adapter = SmartImageAdapter(
        SmartImageSettings(executable=tmp_path / "SmartImage.exe")
    )

    with pytest.raises(SmartImageExecutionError, match="image file not found"):
        adapter(reverse_image_action(str(tmp_path / "missing.jpg")))

    assert calls == []


def test_smartimage_adapter_reports_child_failure(monkeypatch, tmp_path: Path):
    executable = tmp_path / "SmartImage.exe"
    executable.write_bytes(b"fixture")
    image = tmp_path / "sample.jpg"
    image.write_bytes(b"image")

    monkeypatch.setattr(
        "private_search.osint.smartimage.subprocess.run",
        lambda *args, **kwargs: type(
            "Completed", (), {"returncode": 2, "stdout": "", "stderr": "bad input"}
        )(),
    )
    adapter = SmartImageAdapter(
        SmartImageSettings(executable=executable, timeout_seconds=5)
    )

    with pytest.raises(SmartImageExecutionError, match="exited with code 2: bad input"):
        adapter(reverse_image_action(str(image)))


def test_smartimage_adapter_falls_back_to_dotnet_when_exe_is_blocked(
    monkeypatch, tmp_path: Path
):
    executable = tmp_path / "SmartImage.exe"
    dotnet = tmp_path / "dotnet.exe"
    managed = tmp_path / "SmartImage.dll"
    image = tmp_path / "sample.jpg"
    for path in (executable, dotnet, managed, image):
        path.write_bytes(b"fixture")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            error = OSError("blocked")
            error.winerror = 4551
            raise error
        output = Path(command[command.index("--output-file") + 1])
        output.write_text("Name|Url\nFallback|https://example.test\n", encoding="utf-8")
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("private_search.osint.smartimage.subprocess.run", fake_run)
    adapter = SmartImageAdapter(
        SmartImageSettings(
            executable=executable,
            dotnet=dotnet,
            managed_entrypoint=managed,
        )
    )

    results = adapter(reverse_image_action(str(image)))

    assert results[0]["name"] == "Fallback"
    assert calls[0][0] == str(executable)
    assert calls[1][:2] == [str(dotnet), str(managed)]


def test_smartimage_adapter_explains_catbox_socket_failures(monkeypatch, tmp_path: Path):
    executable = tmp_path / "SmartImage.exe"
    image = tmp_path / "sample.jpg"
    executable.write_bytes(b"fixture")
    image.write_bytes(b"image")
    monkeypatch.setattr(
        "private_search.osint.smartimage.subprocess.run",
        lambda *args, **kwargs: type(
            "Completed",
            (),
            {
                "returncode": -1,
                "stdout": "",
                "stderr": "socket denied (catbox.moe:443)",
            },
        )(),
    )
    adapter = SmartImageAdapter(SmartImageSettings(executable=executable))

    with pytest.raises(SmartImageExecutionError, match="Catbox upload service"):
        adapter(reverse_image_action(str(image)))


def test_smartimage_adapter_explains_catbox_timeout(monkeypatch, tmp_path: Path):
    executable = tmp_path / "SmartImage.exe"
    image = tmp_path / "sample.jpg"
    executable.write_bytes(b"fixture")
    image.write_bytes(b"image")
    monkeypatch.setattr(
        "private_search.osint.smartimage.subprocess.run",
        lambda *args, **kwargs: type(
            "Completed",
            (),
            {
                "returncode": -1,
                "stdout": "Error: Call timed out: POST https://catbox.moe/user/api.php",
                "stderr": "",
            },
        )(),
    )
    adapter = SmartImageAdapter(SmartImageSettings(executable=executable))

    with pytest.raises(SmartImageExecutionError, match="timed out or could not be reached"):
        adapter(reverse_image_action(str(image)))


def test_smartimage_search_image_uses_internal_seam(monkeypatch, tmp_path: Path):
    executable = tmp_path / "SmartImage.exe"
    image = tmp_path / "sample.jpg"
    executable.write_bytes(b"fixture")
    image.write_bytes(b"image")
    calls: list[Path] = []

    def fake_search(self, path: Path):
        calls.append(path)
        return [{"url": "https://example.test/result"}]

    monkeypatch.setattr(SmartImageAdapter, "search_image", fake_search)
    adapter = SmartImageAdapter(SmartImageSettings(executable=executable))

    results = adapter(reverse_image_action(str(image)))

    assert results == [{"url": "https://example.test/result"}]
    assert calls == [image.resolve()]
