from __future__ import annotations

import asyncio
import builtins
import importlib.util
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "theia_worker.py"
HTTP_CLIENT_PATH = ROOT / "src" / "modules" / "utils" / "http_client.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.pop(name, None)
    spec.loader.exec_module(module)
    return module


def test_theia_worker_import_does_not_load_cli_entrypoint(monkeypatch):
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "blackbird":
            raise AssertionError("CLI entrypoint import is forbidden")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    load_module(WORKER_PATH, "blackbird_theia_worker_no_cli")


def test_sync_http_client_enables_tls_verification(monkeypatch):
    module = load_module(HTTP_CLIENT_PATH, "blackbird_http_client_sync")
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(module.requests, "request", fake_request)
    config = SimpleNamespace(
        userAgent="agent",
        timeout=7,
        proxy=None,
        verbose=False,
        console=None,
    )

    module.do_sync_request("GET", "https://example.test", config)

    assert calls[0]["verify"] is True


def test_async_http_client_enables_tls_verification():
    module = load_module(HTTP_CLIENT_PATH, "blackbird_http_client_async")
    calls = []

    class FakeResponse:
        status = 200

        def __init__(self):
            self.headers = {}

        async def text(self):
            return "ok"

        async def read(self):
            return b"ok"

    class FakeSession:
        async def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return FakeResponse()

    config = SimpleNamespace(
        userAgent="agent",
        timeout=7,
        proxy=None,
        verbose=False,
        console=None,
    )

    asyncio.run(
        module.do_async_request("GET", "https://example.test", FakeSession(), config)
    )

    assert calls[0][2]["ssl"] is True


def test_theia_worker_emits_one_json_value_and_keeps_ai_disabled(
    monkeypatch, tmp_path: Path, capsys
):
    module = load_module(WORKER_PATH, "blackbird_theia_worker_success")
    updates = []

    def fake_check_updates(config):
        updates.append(config.USERNAME_LIST_PATH)

    def fake_verify_username(username, config):
        assert username == "alice"
        assert config.ai is False
        assert config.setup_ai is False
        assert config.api_url is None
        assert config.max_concurrent_requests == 7
        assert Path(config.USERNAME_LIST_PATH).is_absolute()
        assert Path(config.USERNAME_LIST_PATH).parent == ROOT / "data"
        config.console.print("worker diagnostic")
        return [
            {
                "name": "GitHub",
                "url": "https://github.com/alice",
                "status": "FOUND",
                "category": "social",
                "metadata": [],
            }
        ]

    monkeypatch.setattr(module, "checkUpdates", fake_check_updates)
    monkeypatch.setattr(module, "verifyUsername", fake_verify_username)
    monkeypatch.setenv("PRIVATE_SEARCH_BLACKBIRD_THREADS", "7")
    monkeypatch.setenv("PRIVATE_SEARCH_BLACKBIRD_TIMEOUT", "13")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO('{"operation":"username","value":"alice","update_sites":true}'),
    )

    assert module.main() == 0

    captured = capsys.readouterr()
    assert updates == [str(ROOT / "data" / "wmn-data.json")]
    assert captured.out == (
        '[{"source":"blackbird","kind":"username","site":"GitHub",'
        '"url":"https://github.com/alice","status":"FOUND","category":"social",'
        '"metadata":[]}]'
    )
    assert "worker diagnostic" in captured.err


@pytest.mark.parametrize(
    ("request_text", "message"),
    [
        ('{"operation":"user","value":"alice"}', "operation"),
        ('{"operation":"username","value":"-bad"}', "valid username"),
        ('{"operation":"email","value":"not-an-email"}', "valid email"),
    ],
)
def test_theia_worker_rejects_invalid_requests_before_network(
    monkeypatch, capsys, request_text: str, message: str
):
    module = load_module(WORKER_PATH, f"blackbird_theia_worker_invalid_{hash(request_text)}")
    monkeypatch.setattr(
        module,
        "verifyUsername",
        lambda *args, **kwargs: pytest.fail("network work should not run"),
    )
    monkeypatch.setattr(
        module,
        "verifyEmail",
        lambda *args, **kwargs: pytest.fail("network work should not run"),
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(request_text))

    assert module.main() == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err


def test_theia_worker_reports_update_failure(monkeypatch, capsys):
    module = load_module(WORKER_PATH, "blackbird_theia_worker_update_failure")
    monkeypatch.setattr(
        module,
        "checkUpdates",
        lambda config: (_ for _ in ()).throw(RuntimeError("update failed")),
    )
    monkeypatch.setattr(
        module,
        "verifyUsername",
        lambda *args, **kwargs: pytest.fail("search should not run after update failure"),
    )
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO('{"operation":"username","value":"alice","update_sites":true}'),
    )

    assert module.main() == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "update failed" in captured.err
