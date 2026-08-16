"""Isolated JSON-worker adapter for Blackbird OSINT lookups."""

from __future__ import annotations

import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .. import config
from ..ai.actions import AgentAction
from .worker import WorkerExecutionError, run_json_worker

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class BlackbirdExecutionError(RuntimeError):
    """Raised when Blackbird cannot be configured or complete a lookup."""


def _default_python(root: Path) -> Path:
    configured = os.environ.get("PRIVATE_SEARCH_BLACKBIRD_PYTHON", "").strip()
    if configured:
        return Path(configured).expanduser()
    for candidate in (
        root / ".venv" / "Scripts" / "python.exe",
        root / "venv" / "Scripts" / "python.exe",
    ):
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


def _parse_bool(value: str, *, default: bool) -> bool:
    text = value.strip().casefold()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise BlackbirdExecutionError(f"invalid Blackbird update policy: {value}")


@dataclass(frozen=True)
class BlackbirdSettings:
    """Runtime settings for the isolated Blackbird worker."""

    root: Path
    python: Path
    timeout_seconds: int = 300
    threads: int = 8
    update_sites: bool = True

    @classmethod
    def from_environment(cls) -> BlackbirdSettings:
        configured_root = os.environ.get("PRIVATE_SEARCH_BLACKBIRD_ROOT", "").strip()
        root = (
            Path(configured_root).expanduser()
            if configured_root
            else config.PROJECT_ROOT / "Update" / "blackbird"
        )
        timeout = int(os.environ.get("PRIVATE_SEARCH_BLACKBIRD_TIMEOUT", "300"))
        threads = int(os.environ.get("PRIVATE_SEARCH_BLACKBIRD_THREADS", "8"))
        update_sites = _parse_bool(
            os.environ.get("PRIVATE_SEARCH_BLACKBIRD_UPDATE_SITES", "1"),
            default=True,
        )
        python = _default_python(root)
        return cls(
            root=root,
            python=python,
            timeout_seconds=timeout,
            threads=threads,
            update_sites=update_sites,
        )


class BlackbirdAdapter:
    """Run one explicit username or email lookup through the Blackbird worker."""

    def __init__(self, settings: BlackbirdSettings | None = None) -> None:
        self.settings = settings or BlackbirdSettings.from_environment()

    def __call__(self, action: AgentAction) -> list[dict[str, object]]:
        operation, value = self._resolve_action(action)
        root = self.settings.root.expanduser().resolve()
        worker = root / "theia_worker.py"
        python = self.settings.python.expanduser().resolve()
        if not worker.is_file():
            raise BlackbirdExecutionError(f"Blackbird worker not found: {worker}")
        if not python.is_file():
            raise BlackbirdExecutionError(
                f"Blackbird Python runtime not found: {python}. "
                "Create Update/blackbird/.venv or set PRIVATE_SEARCH_BLACKBIRD_PYTHON."
            )
        if self.settings.timeout_seconds < 1:
            raise BlackbirdExecutionError("Blackbird timeout must be at least 1 second")
        if self.settings.threads < 1:
            raise BlackbirdExecutionError("Blackbird thread count must be at least 1")

        command = [str(python), str(worker)]
        request = {
            "operation": operation,
            "value": value,
            "update_sites": self.settings.update_sites,
        }
        try:
            with tempfile.TemporaryDirectory(prefix="private-search-blackbird-") as workdir:
                payload = run_json_worker(
                    command,
                    request,
                    cwd=Path(workdir),
                    timeout_seconds=self.settings.timeout_seconds,
                    env=self._worker_env(),
                )
        except WorkerExecutionError as error:
            raise BlackbirdExecutionError(str(error)) from error

        if not isinstance(payload, list):
            raise BlackbirdExecutionError("Blackbird worker returned an unexpected response")
        return self._normalize_results(payload, kind=operation)

    def _worker_env(self) -> dict[str, str]:
        keep = (
            "APPDATA",
            "COMSPEC",
            "LOCALAPPDATA",
            "OS",
            "PATH",
            "PATHEXT",
            "PROGRAMDATA",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "WINDIR",
        )
        env = {
            key: value
            for key in keep
            if (value := os.environ.get(key))
        }
        env["PRIVATE_SEARCH_BLACKBIRD_THREADS"] = str(self.settings.threads)
        env["PRIVATE_SEARCH_BLACKBIRD_TIMEOUT"] = str(self.settings.timeout_seconds)
        env["PRIVATE_SEARCH_BLACKBIRD_UPDATE_SITES"] = (
            "1" if self.settings.update_sites else "0"
        )
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        return env

    @classmethod
    def _resolve_action(cls, action: object) -> tuple[str, str]:
        action_name = getattr(action, "action", None)
        if action_name == "username_osint":
            value = getattr(action, "username", None)
            cls._validate_username(value)
            assert isinstance(value, str)
            return "username", value
        if action_name == "email_osint":
            value = getattr(action, "email", None)
            cls._validate_email(value)
            assert isinstance(value, str)
            return "email", value
        raise BlackbirdExecutionError(f"unsupported Blackbird action: {action_name}")

    @staticmethod
    def _validate_username(username: object) -> None:
        if not isinstance(username, str) or not username.strip():
            raise BlackbirdExecutionError("username must be a valid username")
        if len(username) > 128 or username.startswith("-"):
            raise BlackbirdExecutionError("username must be a valid username")
        if any(character in username for character in ("/", "\\", "\x00")):
            raise BlackbirdExecutionError("username must be a valid username")
        if any(ord(character) < 32 or ord(character) == 127 for character in username):
            raise BlackbirdExecutionError("username must be a valid username")

    @staticmethod
    def _validate_email(email: object) -> None:
        if not isinstance(email, str) or not _EMAIL_PATTERN.fullmatch(email.strip()):
            raise BlackbirdExecutionError("email must be a valid email")

    @staticmethod
    def _normalize_results(
        records: list[object], *, kind: str
    ) -> list[dict[str, object]]:
        normalized: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()
        for record in records:
            if not isinstance(record, dict):
                raise BlackbirdExecutionError("Blackbird worker returned an unexpected record")
            site = record.get("site") or record.get("name")
            url = record.get("url")
            if not isinstance(site, str) or not site.strip():
                raise BlackbirdExecutionError("Blackbird worker returned a record without a site")
            if not isinstance(url, str) or not url.strip():
                raise BlackbirdExecutionError("Blackbird worker returned a record without a URL")
            key = (site.casefold(), url)
            if key in seen:
                continue
            seen.add(key)
            metadata = record.get("metadata")
            normalized.append(
                {
                    "source": "blackbird",
                    "kind": kind,
                    "site": site,
                    "url": url,
                    "status": record.get("status", "UNKNOWN"),
                    "category": record.get("category"),
                    "metadata": metadata if isinstance(metadata, list) else [],
                }
            )
        return normalized


__all__ = [
    "BlackbirdAdapter",
    "BlackbirdExecutionError",
    "BlackbirdSettings",
]
