"""Confirmation-gated subprocess adapter for SmartImage Rdx."""

from __future__ import annotations

import csv
import os
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .. import config
from ..progress import ProgressEvent

if TYPE_CHECKING:
    from ..ai.actions import AgentAction


class SmartImageExecutionError(RuntimeError):
    """Raised when SmartImage cannot complete a reverse-image search."""


def _default_executable() -> Path:
    configured = os.environ.get("PRIVATE_SEARCH_SMARTIMAGE_RDX", "").strip()
    if configured:
        return Path(configured).expanduser()
    return config.PROJECT_ROOT / "var" / "smartimage-rdx" / "SmartImage.exe"


def _default_dotnet() -> Path:
    configured = os.environ.get("PRIVATE_SEARCH_SMARTIMAGE_DOTNET", "").strip()
    if configured:
        return Path(configured).expanduser()
    return config.RUNTIME_ROOT / "dotnet" / "dotnet.exe"


def _default_managed_entrypoint() -> Path:
    configured = os.environ.get("PRIVATE_SEARCH_SMARTIMAGE_DLL", "").strip()
    if configured:
        return Path(configured).expanduser()
    return config.PROJECT_ROOT / "var" / "smartimage-rdx-host" / "SmartImage.dll"


@dataclass(frozen=True)
class SmartImageSettings:
    """Runtime settings for the published SmartImage Rdx subprocess."""

    executable: Path
    timeout_seconds: int = 300
    dotnet: Path | None = None
    managed_entrypoint: Path | None = None
    upload_engine: str = "TmpFiles"

    @classmethod
    def from_environment(cls) -> SmartImageSettings:
        timeout = int(os.environ.get("PRIVATE_SEARCH_SMARTIMAGE_TIMEOUT", "300"))
        return cls(
            executable=_default_executable(),
            timeout_seconds=timeout,
            dotnet=_default_dotnet(),
            managed_entrypoint=_default_managed_entrypoint(),
            upload_engine=os.environ.get("PRIVATE_SEARCH_SMARTIMAGE_UPLOAD_ENGINE", "TmpFiles").strip()
            or "TmpFiles",
        )


class SmartImageAdapter:
    """Run SmartImage Rdx in machine-readable, non-interactive mode."""

    _DELIMITER = "|"
    _FIELDS = "Name,Url,Similarity,Artist,Site"
    _UPLOAD_ENGINES = frozenset({"Catbox", "Litterbox", "Pomf", "TmpFiles"})

    def __init__(self, settings: SmartImageSettings | None = None) -> None:
        self.settings = settings or SmartImageSettings.from_environment()

    def __call__(
        self,
        action: AgentAction,
        *,
        progress: Callable[[ProgressEvent], None] | None = None,
    ) -> object:
        image_path = action.image_path
        if image_path is None:
            raise SmartImageExecutionError("image_path is required for SmartImage")
        image = Path(image_path).expanduser().resolve()
        if progress is None:
            return self.search_image(image)
        return self.search_image(image, progress=progress)

    def search_image(
        self,
        path: Path,
        *,
        progress: Callable[[ProgressEvent], None] | None = None,
    ) -> list[dict[str, str]]:
        image = path.expanduser().resolve()
        if not image.is_file():
            raise SmartImageExecutionError(f"image file not found: {image}")

        executable = self.settings.executable.expanduser().resolve()
        if not executable.is_file():
            raise SmartImageExecutionError(
                f"SmartImage executable not found: {executable}. "
                "Build or publish SmartImage.Rdx first, or set PRIVATE_SEARCH_SMARTIMAGE_RDX."
            )
        if self.settings.timeout_seconds < 1:
            raise SmartImageExecutionError("SmartImage timeout must be at least 1 second")
        if self.settings.upload_engine not in self._UPLOAD_ENGINES:
            allowed = ", ".join(sorted(self._UPLOAD_ENGINES))
            raise SmartImageExecutionError(
                f"unsupported SmartImage upload engine: {self.settings.upload_engine}. "
                f"Choose one of: {allowed}"
            )

        self._emit(
            progress,
            "upload",
            "Uploading image to SmartImage",
            completed=0,
            total=3,
        )

        with tempfile.TemporaryDirectory(prefix="theia-smartimage-") as workdir:
            output = Path(workdir) / "results.delimited"
            novus_data = Path(workdir) / "novus"
            arguments = [
                str(image),
                "--upload-engine",
                self.settings.upload_engine,
                "--interactive",
                "false",
                "--output-format",
                "Delimited",
                "--output-file",
                str(output),
                "--output-delim",
                self._DELIMITER,
                "--output-fields",
                self._FIELDS,
            ]
            command = [str(executable), *arguments]
            environment = os.environ.copy()
            environment["NOVUS_DATA_FOLDER"] = str(novus_data)
            self._emit(
                progress,
                "upload",
                "Submitting image to SmartImage",
                completed=1,
                total=3,
            )
            try:
                completed = self._run(command, workdir, environment)
            except subprocess.TimeoutExpired as error:
                raise SmartImageExecutionError(
                    f"SmartImage timed out after {self.settings.timeout_seconds} seconds"
                ) from error
            except OSError as error:
                if not self._is_application_control_block(error):
                    raise SmartImageExecutionError(f"could not start SmartImage: {error}") from error
                fallback = self._fallback_command(arguments)
                if fallback is None:
                    raise SmartImageExecutionError(
                        "could not start SmartImage: Windows application-control policy blocked "
                        "the executable and no local dotnet fallback is configured"
                    ) from error
                try:
                    completed = self._run(fallback, workdir, environment)
                except (OSError, subprocess.TimeoutExpired) as fallback_error:
                    raise SmartImageExecutionError(
                        f"could not start SmartImage through the local dotnet fallback: {fallback_error}"
                    ) from fallback_error

            if completed.returncode != 0:
                detail = self._failure_detail(completed)
                raise SmartImageExecutionError(
                    f"SmartImage exited with code {completed.returncode}: {detail}"
                )
            if not output.is_file():
                detail = (completed.stderr or completed.stdout or "no output file was produced").strip()
                raise SmartImageExecutionError(f"SmartImage produced no results file: {detail[-800:]}")

            try:
                self._emit(
                    progress,
                    "parse",
                    "Parsing SmartImage results",
                    completed=2,
                    total=3,
                )
                with output.open("r", encoding="utf-8", newline="") as stream:
                    rows = csv.DictReader(stream, delimiter=self._DELIMITER)
                    results = [
                        {
                            "name": row.get("Name", ""),
                            "url": row.get("Url", ""),
                            "similarity": row.get("Similarity", ""),
                            "artist": row.get("Artist", ""),
                            "site": row.get("Site", ""),
                        }
                        for row in rows
                    ]
                    self._emit(
                        progress,
                        "complete",
                        f"SmartImage returned {len(results)} result(s)",
                        completed=3,
                        total=3,
                    )
                    return results
            except (OSError, csv.Error) as error:
                raise SmartImageExecutionError(
                    f"SmartImage produced an invalid delimited report: {error}"
                ) from error

    @staticmethod
    def _emit(
        progress: Callable[[ProgressEvent], None] | None,
        phase: str,
        message: str,
        *,
        completed: int,
        total: int,
    ) -> None:
        if progress is None:
            return
        progress(
            ProgressEvent(
                phase=phase,
                message=message,
                completed=completed,
                total=total,
            )
        )

    def _run(self, command: list[str], workdir: str, environment: dict[str, str]):
        return subprocess.run(
            command,
            cwd=workdir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.settings.timeout_seconds,
            env=environment,
            shell=False,
            check=False,
        )

    def _fallback_command(self, arguments: list[str]) -> list[str] | None:
        dotnet = self.settings.dotnet
        managed_entrypoint = self.settings.managed_entrypoint
        if dotnet is None or managed_entrypoint is None:
            return None
        dotnet = dotnet.expanduser().resolve()
        managed_entrypoint = managed_entrypoint.expanduser().resolve()
        if not dotnet.is_file() or not managed_entrypoint.is_file():
            return None
        return [str(dotnet), str(managed_entrypoint), *arguments]

    @staticmethod
    def _failure_detail(completed: object) -> str:
        detail = (completed.stderr or completed.stdout or "no diagnostic output").strip()
        lowered = detail.casefold()
        if "catbox.moe" in lowered and ("socket" in lowered or "timed out" in lowered):
            return (
                "the Catbox upload service timed out or could not be reached; check firewall/network "
                "policy or explicitly configure another SmartImage upload engine"
            )
        return detail[-800:]

    @staticmethod
    def _is_application_control_block(error: OSError) -> bool:
        return getattr(error, "winerror", None) == 4551
