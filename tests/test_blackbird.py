from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from private_search.ai.actions import AgentAction
from private_search.osint.blackbird import (
    BlackbirdAdapter,
    BlackbirdExecutionError,
    BlackbirdSettings,
)


def username_action(username: str = "alice") -> AgentAction:
    return AgentAction(
        action="username_osint",
        reason="The user explicitly requested a username lookup.",
        username=username,
    )


def email_action(email: str = "alice@example.com") -> object:
    return SimpleNamespace(
        action="email_osint",
        reason="The user explicitly requested an email lookup.",
        email=email,
    )


def test_blackbird_settings_from_environment(monkeypatch, tmp_path: Path):
    root = tmp_path / "blackbird"
    root.mkdir()
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    monkeypatch.setenv("PRIVATE_SEARCH_BLACKBIRD_ROOT", str(root))
    monkeypatch.setenv("PRIVATE_SEARCH_BLACKBIRD_PYTHON", str(python))
    monkeypatch.setenv("PRIVATE_SEARCH_BLACKBIRD_TIMEOUT", "41")
    monkeypatch.setenv("PRIVATE_SEARCH_BLACKBIRD_THREADS", "6")
    monkeypatch.setenv("PRIVATE_SEARCH_BLACKBIRD_UPDATE_SITES", "0")

    settings = BlackbirdSettings.from_environment()

    assert settings.root == root
    assert settings.python == python
    assert settings.timeout_seconds == 41
    assert settings.threads == 6
    assert settings.update_sites is False


def test_blackbird_adapter_runs_username_worker_in_isolated_directory(
    monkeypatch, tmp_path: Path
):
    root = tmp_path / "blackbird"
    root.mkdir()
    worker = root / "theia_worker.py"
    worker.write_text("# fixture", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    calls: list[tuple[list[str], dict[str, object], Path, int, dict[str, str] | None]] = []

    def fake_run_json_worker(
        command,
        request,
        *,
        cwd,
        timeout_seconds,
        env=None,
    ):
        assert cwd.is_dir()
        assert cwd != root
        calls.append((command, request, cwd, timeout_seconds, env))
        return [
            {
                "name": "GitHub",
                "url": "https://github.com/alice",
                "status": "FOUND",
                "category": "social",
                "metadata": [],
            },
            {
                "site": "GitHub",
                "url": "https://github.com/alice",
                "status": "FOUND",
                "category": "social",
                "metadata": [],
            },
        ]

    monkeypatch.setattr(
        "private_search.osint.blackbird.run_json_worker", fake_run_json_worker
    )
    adapter = BlackbirdAdapter(
        BlackbirdSettings(
            root=root,
            python=python,
            timeout_seconds=9,
            threads=7,
            update_sites=True,
        )
    )

    results = adapter(username_action())

    assert results == [
        {
            "source": "blackbird",
            "kind": "username",
            "site": "GitHub",
            "url": "https://github.com/alice",
            "status": "FOUND",
            "category": "social",
            "metadata": [],
        }
    ]
    command, request, _, timeout_seconds, env = calls[0]
    assert command == [str(python), str(worker)]
    assert request == {
        "operation": "username",
        "value": "alice",
        "update_sites": True,
    }
    assert timeout_seconds == 9
    assert env is not None
    assert env["PRIVATE_SEARCH_BLACKBIRD_THREADS"] == "7"
    assert env["PRIVATE_SEARCH_BLACKBIRD_TIMEOUT"] == "9"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"


def test_blackbird_adapter_uses_email_operation(monkeypatch, tmp_path: Path):
    root = tmp_path / "blackbird"
    root.mkdir()
    worker = root / "theia_worker.py"
    worker.write_text("# fixture", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    requests: list[dict[str, object]] = []

    def fake_run_json_worker(command, request, **kwargs):
        assert command == [str(python), str(worker)]
        requests.append(request)
        return []

    monkeypatch.setattr(
        "private_search.osint.blackbird.run_json_worker", fake_run_json_worker
    )
    adapter = BlackbirdAdapter(
        BlackbirdSettings(root=root, python=python, timeout_seconds=5, threads=3)
    )

    assert adapter(email_action()) == []
    assert requests == [
        {
            "operation": "email",
            "value": "alice@example.com",
            "update_sites": True,
        }
    ]


@pytest.mark.parametrize(
    ("action", "message"),
    [
        (username_action("-blocked"), "valid username"),
        (email_action("not-an-email"), "valid email"),
    ],
)
def test_blackbird_adapter_validates_values_before_worker(
    monkeypatch, tmp_path: Path, action: object, message: str
):
    calls: list[object] = []
    monkeypatch.setattr(
        "private_search.osint.blackbird.run_json_worker",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    adapter = BlackbirdAdapter(
        BlackbirdSettings(root=tmp_path, python=tmp_path / "python.exe")
    )

    with pytest.raises(BlackbirdExecutionError, match=message):
        adapter(action)

    assert calls == []
