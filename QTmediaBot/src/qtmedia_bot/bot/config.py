"""Environment-backed settings for the Telegram bot runtime."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .services.yt_options import configured_cookie_browser

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_JOB_ROOT = PROJECT_ROOT / "var" / "telegram_jobs"
DEFAULT_METADATA_DB_PATH = PROJECT_ROOT / "var" / "telegram_state" / "metadata.sqlite3"


def _parse_bool(name: str, value: str, *, default: bool) -> bool:
    normalized = value.strip().casefold()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _parse_user_ids(value: str) -> frozenset[int]:
    user_ids: set[int] = set()
    for raw_user_id in value.split(","):
        item = raw_user_id.strip()
        if not item:
            continue
        try:
            user_ids.add(int(item))
        except ValueError as exc:
            raise ValueError(
                "TELEGRAM_ALLOWED_USER_IDS must contain comma-separated integers"
            ) from exc
    return frozenset(user_ids)


def _parse_bot_token(value: str) -> str:
    """Reject missing or obvious placeholder tokens without logging them."""

    token = value.strip()
    if not token or token.casefold() in {
        "replace_me",
        "your_bot_token",
        "changeme",
    }:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")
    return token


def _parse_domains(value: str) -> frozenset[str]:
    domains: set[str] = set()
    for raw_domain in value.split(","):
        domain = raw_domain.strip().casefold().rstrip(".")
        if not domain:
            continue
        if "://" in domain or "/" in domain or "@" in domain:
            raise ValueError(
                "TELEGRAM_ALLOWED_DOMAINS must contain hostnames, not URLs"
            )
        domains.add(domain.removeprefix("www."))
    return frozenset(domains)


def _parse_positive_int(name: str, value: str, default: int) -> int:
    try:
        parsed = int(value.strip()) if value.strip() else default
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


@dataclass(frozen=True, slots=True)
# pylint: disable=too-many-instance-attributes
class BotSettings:
    """Validated configuration needed to construct the Telegram application."""

    token: str
    base_url: str
    file_base_url: str
    local_mode: bool
    private_chats_only: bool
    allowed_user_ids: frozenset[int]
    allowed_domains: frozenset[str] = frozenset()
    max_upload_bytes: int = 1_800_000_000
    max_duration_seconds: int = 3_600
    job_ttl_seconds: int = 3_600
    job_root: Path = DEFAULT_JOB_ROOT
    metadata_db_path: Path = DEFAULT_METADATA_DB_PATH
    metadata_ttl_seconds: int = 900
    orphan_job_ttl_seconds: int = 900
    unconfirmed_upload_retention_seconds: int = 900
    max_concurrent_jobs: int = 1
    disk_reserve_bytes: int = 500_000_000
    download_timeout_seconds: int = 7_200
    upload_timeout_seconds: int = 7_200
    progress_update_seconds: int = 10
    rate_limit_requests: int = 5
    rate_limit_window_seconds: int = 60
    max_queued_jobs: int = 2

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None
    ) -> BotSettings:
        """Build validated settings from a supplied or process environment."""

        values = os.environ if environ is None else environ
        token = _parse_bot_token(values.get("TELEGRAM_BOT_TOKEN", ""))

        allowed_user_ids = _parse_user_ids(
            values.get("TELEGRAM_ALLOWED_USER_IDS", "")
        )
        private_chats_only = _parse_bool(
            "TELEGRAM_PRIVATE_CHATS_ONLY",
            values.get("TELEGRAM_PRIVATE_CHATS_ONLY", "1"),
            default=True,
        )
        if configured_cookie_browser(
            values.get("PRIVATE_SEARCH_YTDLP_COOKIES_FROM_BROWSER", "")
        ) and (len(allowed_user_ids) != 1 or not private_chats_only):
            raise ValueError(
                "browser cookies require exactly one TELEGRAM_ALLOWED_USER_IDS "
                "value and TELEGRAM_PRIVATE_CHATS_ONLY=1"
            )

        return cls(
            token=token,
            base_url=values.get(
                "TELEGRAM_BASE_URL", "https://api.telegram.org/bot"
            ).strip(),
            file_base_url=values.get(
                "TELEGRAM_FILE_BASE_URL", "https://api.telegram.org/file/bot"
            ).strip(),
            local_mode=_parse_bool(
                "TELEGRAM_LOCAL_MODE",
                values.get("TELEGRAM_LOCAL_MODE", "0"),
                default=False,
            ),
            private_chats_only=private_chats_only,
            allowed_user_ids=allowed_user_ids,
            allowed_domains=_parse_domains(
                values.get("TELEGRAM_ALLOWED_DOMAINS", "")
            ),
            max_upload_bytes=_parse_positive_int(
                "TELEGRAM_MAX_UPLOAD_BYTES",
                values.get("TELEGRAM_MAX_UPLOAD_BYTES", "1800000000"),
                1_800_000_000,
            ),
            max_duration_seconds=_parse_positive_int(
                "TELEGRAM_MAX_DURATION_SECONDS",
                values.get("TELEGRAM_MAX_DURATION_SECONDS", "3600"),
                3_600,
            ),
            job_ttl_seconds=_parse_positive_int(
                "TELEGRAM_JOB_TTL_SECONDS",
                values.get("TELEGRAM_JOB_TTL_SECONDS", "3600"),
                3_600,
            ),
            job_root=Path(
                values.get("TELEGRAM_JOB_ROOT", str(DEFAULT_JOB_ROOT)).strip()
                or str(DEFAULT_JOB_ROOT)
            ),
            metadata_db_path=Path(
                values.get(
                    "TELEGRAM_METADATA_DB", str(DEFAULT_METADATA_DB_PATH)
                ).strip()
                or str(DEFAULT_METADATA_DB_PATH)
            ),
            metadata_ttl_seconds=_parse_positive_int(
                "TELEGRAM_METADATA_TTL_SECONDS",
                values.get("TELEGRAM_METADATA_TTL_SECONDS", "900"),
                900,
            ),
            orphan_job_ttl_seconds=_parse_positive_int(
                "TELEGRAM_ORPHAN_JOB_TTL_SECONDS",
                values.get("TELEGRAM_ORPHAN_JOB_TTL_SECONDS", "900"),
                900,
            ),
            unconfirmed_upload_retention_seconds=_parse_positive_int(
                "TELEGRAM_UNCONFIRMED_UPLOAD_RETENTION_SECONDS",
                values.get(
                    "TELEGRAM_UNCONFIRMED_UPLOAD_RETENTION_SECONDS", "900"
                ),
                900,
            ),
            max_concurrent_jobs=_parse_positive_int(
                "TELEGRAM_MAX_CONCURRENT_JOBS",
                values.get("TELEGRAM_MAX_CONCURRENT_JOBS", "1"),
                1,
            ),
            disk_reserve_bytes=_parse_positive_int(
                "TELEGRAM_DISK_RESERVE_BYTES",
                values.get("TELEGRAM_DISK_RESERVE_BYTES", "500000000"),
                500_000_000,
            ),
            download_timeout_seconds=_parse_positive_int(
                "TELEGRAM_DOWNLOAD_TIMEOUT_SECONDS",
                values.get("TELEGRAM_DOWNLOAD_TIMEOUT_SECONDS", "7200"),
                7_200,
            ),
            upload_timeout_seconds=_parse_positive_int(
                "TELEGRAM_UPLOAD_TIMEOUT_SECONDS",
                values.get("TELEGRAM_UPLOAD_TIMEOUT_SECONDS", "7200"),
                7_200,
            ),
            progress_update_seconds=_parse_positive_int(
                "TELEGRAM_PROGRESS_UPDATE_SECONDS",
                values.get("TELEGRAM_PROGRESS_UPDATE_SECONDS", "10"),
                10,
            ),
            rate_limit_requests=_parse_positive_int(
                "TELEGRAM_RATE_LIMIT_REQUESTS",
                values.get("TELEGRAM_RATE_LIMIT_REQUESTS", "5"),
                5,
            ),
            rate_limit_window_seconds=_parse_positive_int(
                "TELEGRAM_RATE_LIMIT_WINDOW_SECONDS",
                values.get("TELEGRAM_RATE_LIMIT_WINDOW_SECONDS", "60"),
                60,
            ),
            max_queued_jobs=_parse_positive_int(
                "TELEGRAM_MAX_QUEUED_JOBS",
                values.get("TELEGRAM_MAX_QUEUED_JOBS", "2"),
                2,
            ),
        )
