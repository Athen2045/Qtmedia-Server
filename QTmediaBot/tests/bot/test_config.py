from pathlib import Path

import pytest

from qtmedia_bot.bot.config import BotSettings


def test_settings_require_a_nonempty_bot_token():
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        BotSettings.from_env({"TELEGRAM_BOT_TOKEN": "  "})


def test_settings_reject_obvious_placeholder_bot_token():
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        BotSettings.from_env({"TELEGRAM_BOT_TOKEN": "replace_me"})


def test_settings_parse_urls_local_mode_and_user_allowlist():
    settings = BotSettings.from_env(
        {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_BASE_URL": "http://api:8081/bot",
            "TELEGRAM_FILE_BASE_URL": "http://api:8081/file/bot",
            "TELEGRAM_LOCAL_MODE": "1",
            "TELEGRAM_ALLOWED_USER_IDS": "12, 34",
        }
    )

    assert settings.base_url == "http://api:8081/bot"
    assert settings.file_base_url == "http://api:8081/file/bot"
    assert settings.local_mode is True
    assert settings.allowed_user_ids == frozenset({12, 34})


def test_settings_reject_non_integer_allowlist_values():
    with pytest.raises(ValueError, match="TELEGRAM_ALLOWED_USER_IDS"):
        BotSettings.from_env(
            {
                "TELEGRAM_BOT_TOKEN": "test-token",
                "TELEGRAM_ALLOWED_USER_IDS": "12,nope",
            }
        )


def test_settings_parse_domains_and_inspection_limits():
    settings = BotSettings.from_env(
        {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_ALLOWED_DOMAINS": "example.com, Sub.Example.org.",
            "TELEGRAM_MAX_UPLOAD_BYTES": "1000000",
            "TELEGRAM_MAX_DURATION_SECONDS": "120",
            "TELEGRAM_JOB_TTL_SECONDS": "300",
        }
    )

    assert settings.allowed_domains == frozenset({"example.com", "sub.example.org"})
    assert settings.max_upload_bytes == 1_000_000
    assert settings.max_duration_seconds == 120
    assert settings.job_ttl_seconds == 300


def test_settings_reject_nonpositive_inspection_limits():
    for name in (
        "TELEGRAM_MAX_UPLOAD_BYTES",
        "TELEGRAM_MAX_DURATION_SECONDS",
        "TELEGRAM_JOB_TTL_SECONDS",
        "TELEGRAM_UPLOAD_TIMEOUT_SECONDS",
        "TELEGRAM_RATE_LIMIT_REQUESTS",
        "TELEGRAM_RATE_LIMIT_WINDOW_SECONDS",
        "TELEGRAM_MAX_QUEUED_JOBS",
    ):
        with pytest.raises(ValueError, match=name):
            BotSettings.from_env(
                {"TELEGRAM_BOT_TOKEN": "test-token", name: "0"}
            )


def test_settings_parse_download_runtime_limits():
    settings = BotSettings.from_env(
        {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_JOB_ROOT": "var/test-telegram-jobs",
            "TELEGRAM_MAX_CONCURRENT_JOBS": "2",
            "TELEGRAM_DISK_RESERVE_BYTES": "500000000",
            "TELEGRAM_DOWNLOAD_TIMEOUT_SECONDS": "900",
        }
    )

    assert settings.job_root == Path("var/test-telegram-jobs")
    assert settings.max_concurrent_jobs == 2
    assert settings.disk_reserve_bytes == 500_000_000
    assert settings.download_timeout_seconds == 900


def test_settings_parse_privacy_retention_paths_and_limits():
    settings = BotSettings.from_env(
        {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_METADATA_DB": "var/test-telegram-state/metadata.sqlite3",
            "TELEGRAM_METADATA_TTL_SECONDS": "1800",
            "TELEGRAM_ORPHAN_JOB_TTL_SECONDS": "1200",
            "TELEGRAM_UNCONFIRMED_UPLOAD_RETENTION_SECONDS": "2400",
        }
    )

    assert settings.metadata_db_path == Path(
        "var/test-telegram-state/metadata.sqlite3"
    )
    assert settings.metadata_ttl_seconds == 1800
    assert settings.orphan_job_ttl_seconds == 1200
    assert settings.unconfirmed_upload_retention_seconds == 2400


def test_settings_parse_upload_timeout():
    settings = BotSettings.from_env(
        {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_UPLOAD_TIMEOUT_SECONDS": "1800",
        }
    )

    assert settings.upload_timeout_seconds == 1800


def test_settings_parse_progress_update_seconds():
    settings = BotSettings.from_env(
        {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_PROGRESS_UPDATE_SECONDS": "12",
        }
    )

    assert settings.progress_update_seconds == 12


def test_settings_parse_admission_limits():
    settings = BotSettings.from_env(
        {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_RATE_LIMIT_REQUESTS": "7",
            "TELEGRAM_RATE_LIMIT_WINDOW_SECONDS": "90",
            "TELEGRAM_MAX_QUEUED_JOBS": "3",
        }
    )

    assert settings.rate_limit_requests == 7
    assert settings.rate_limit_window_seconds == 90
    assert settings.max_queued_jobs == 3


def test_settings_require_user_allowlist_when_browser_cookies_are_enabled():
    with pytest.raises(ValueError, match="TELEGRAM_ALLOWED_USER_IDS"):
        BotSettings.from_env(
            {
                "TELEGRAM_BOT_TOKEN": "test-token",
                "PRIVATE_SEARCH_YTDLP_COOKIES_FROM_BROWSER": "chrome",
            }
        )


def test_settings_accept_browser_cookies_with_user_allowlist():
    settings = BotSettings.from_env(
        {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_ALLOWED_USER_IDS": "123",
            "PRIVATE_SEARCH_YTDLP_COOKIES_FROM_BROWSER": "chrome",
        }
    )

    assert settings.allowed_user_ids == frozenset({123})


def test_settings_reject_multiple_users_or_group_chats_with_browser_cookies():
    with pytest.raises(ValueError, match="TELEGRAM_ALLOWED_USER_IDS"):
        BotSettings.from_env(
            {
                "TELEGRAM_BOT_TOKEN": "test-token",
                "TELEGRAM_ALLOWED_USER_IDS": "123,456",
                "PRIVATE_SEARCH_YTDLP_COOKIES_FROM_BROWSER": "chrome",
            }
        )
    with pytest.raises(ValueError, match="TELEGRAM_PRIVATE_CHATS_ONLY"):
        BotSettings.from_env(
            {
                "TELEGRAM_BOT_TOKEN": "test-token",
                "TELEGRAM_ALLOWED_USER_IDS": "123",
                "TELEGRAM_PRIVATE_CHATS_ONLY": "0",
                "PRIVATE_SEARCH_YTDLP_COOKIES_FROM_BROWSER": "chrome",
            }
        )

