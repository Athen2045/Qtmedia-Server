"""JSON stdin/stdout worker for Blackbird username and email lookups."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from rich.console import Console

USERNAME_LIST_URL = (
    "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-data.json"
)
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

checkUpdates = None
verifyEmail = None
verifyUsername = None


class WorkerInputError(ValueError):
    """Raised when a worker request is malformed or unsafe."""


def main() -> int:
    try:
        request = _read_request(sys.stdin.read())
        root = Path(__file__).resolve().parent
        runtime = _build_runtime(root=root, workdir=Path.cwd().resolve())
        if request["update_sites"]:
            _ensure_check_updates()(runtime)
        if request["operation"] == "username":
            runtime.currentUser = request["value"]
            results = _ensure_username_verifier()(request["value"], runtime)
        else:
            runtime.currentEmail = request["value"]
            results = _ensure_email_verifier()(request["value"], runtime)
        payload = _normalize_records(results, kind=request["operation"])
        sys.stdout.write(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
        sys.stdout.flush()
        return 0
    except Exception as error:  # noqa: BLE001 - the worker must convert any failure into stderr diagnostics and exit 1.
        print(str(error), file=sys.stderr)
        return 1


def _read_request(raw_text: str) -> dict[str, object]:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise WorkerInputError("request must be a JSON object") from error
    if not isinstance(payload, dict):
        raise WorkerInputError("request must be a JSON object")
    operation = payload.get("operation")
    if operation not in {"username", "email"}:
        raise WorkerInputError("operation must be username or email")
    value = payload.get("value")
    if operation == "username":
        _validate_username(value)
    else:
        _validate_email(value)
    update_sites = payload.get("update_sites", True)
    if not isinstance(update_sites, bool):
        raise WorkerInputError("update_sites must be a boolean")
    assert isinstance(value, str)
    return {"operation": operation, "value": value, "update_sites": update_sites}


def _build_runtime(*, root: Path, workdir: Path) -> SimpleNamespace:
    timeout = int(os.environ.get("PRIVATE_SEARCH_BLACKBIRD_TIMEOUT", "300"))
    threads = int(os.environ.get("PRIVATE_SEARCH_BLACKBIRD_THREADS", "8"))
    if timeout < 1:
        raise WorkerInputError("Blackbird timeout must be at least 1 second")
    if threads < 1:
        raise WorkerInputError("Blackbird thread count must be at least 1")

    data_root = root / "data"
    log_root = workdir / "logs"
    log_root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    return SimpleNamespace(
        USERNAME_LIST_URL=USERNAME_LIST_URL,
        USERNAME_LIST_PATH=str(data_root / "wmn-data.json"),
        USERNAME_METADATA_LIST_PATH=str(data_root / "wmn-metadata.json"),
        EMAIL_LIST_PATH=str(data_root / "email-data.json"),
        LOG_PATH=str(log_root / "blackbird.log"),
        console=Console(file=sys.stderr, force_terminal=False, no_color=True),
        no_nsfw=False,
        proxy=None,
        verbose=False,
        timeout=timeout,
        dump=False,
        csv=False,
        pdf=False,
        json=False,
        filter=None,
        ai=False,
        setup_ai=False,
        aiModel=None,
        ai_analysis=None,
        api_url=None,
        instagram_session_id=None,
        max_concurrent_requests=threads,
        currentUser=None,
        currentEmail=None,
        usernameFoundAccounts=None,
        emailFoundAccounts=None,
        dateRaw=now.strftime("%m_%d_%Y"),
        datePretty=now.strftime("%B %d, %Y"),
        userAgent="Mozilla/5.0 (compatible; Theia Blackbird Worker)",
    )


def _normalize_records(records: object, *, kind: str) -> list[dict[str, object]]:
    if not isinstance(records, list):
        raise WorkerInputError("Blackbird returned an unexpected result payload")
    normalized: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        if not isinstance(record, dict):
            raise WorkerInputError("Blackbird returned an unexpected result payload")
        site = record.get("site") or record.get("name")
        url = record.get("url")
        if not isinstance(site, str) or not site.strip():
            raise WorkerInputError("Blackbird returned a record without a site")
        if not isinstance(url, str) or not url.strip():
            raise WorkerInputError("Blackbird returned a record without a URL")
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


def _validate_username(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise WorkerInputError("username must be a valid username")
    if len(value) > 128 or value.startswith("-"):
        raise WorkerInputError("username must be a valid username")
    if any(character in value for character in ("/", "\\", "\x00")):
        raise WorkerInputError("username must be a valid username")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise WorkerInputError("username must be a valid username")


def _validate_email(value: object) -> None:
    if not isinstance(value, str) or not _EMAIL_PATTERN.fullmatch(value.strip()):
        raise WorkerInputError("email must be a valid email")


def _ensure_src_path() -> None:
    src_root = Path(__file__).resolve().parent / "src"
    src_path = str(src_root)
    if src_path not in sys.path:
        sys.path.insert(0, src_path)


def _ensure_check_updates():
    global checkUpdates
    if checkUpdates is None:
        _ensure_src_path()
        from modules.whatsmyname.list_operations import checkUpdates as imported

        checkUpdates = imported
    return checkUpdates


def _ensure_username_verifier():
    global verifyUsername
    if verifyUsername is None:
        _ensure_src_path()
        from modules.core.username import verifyUsername as imported

        verifyUsername = imported
    return verifyUsername


def _ensure_email_verifier():
    global verifyEmail
    if verifyEmail is None:
        _ensure_src_path()
        from modules.core.email import verifyEmail as imported

        verifyEmail = imported
    return verifyEmail


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    raise SystemExit(main())
