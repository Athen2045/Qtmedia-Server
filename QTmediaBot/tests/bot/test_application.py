import asyncio
import logging
import os
import sqlite3
from pathlib import Path

from telegram.ext import CallbackQueryHandler, CommandHandler

from qtmedia_bot.bot import application as application_module
from qtmedia_bot.bot.application import build_application, handle_error
from qtmedia_bot.bot.config import BotSettings
from qtmedia_bot.bot.services.downloads import DownloadManager
from qtmedia_bot.bot.services.inspection import MediaInspection
from qtmedia_bot.bot.services.jobs import JobCatalog
from qtmedia_bot.bot.services.quality import QualityOption
from qtmedia_bot.bot.storage import JobMetadataStore


def _raise_attribute_error() -> None:
    raise AttributeError("sensitive https://secret.example/token")


def test_build_application_registers_commands_and_error_handler():
    settings = BotSettings(
        token="test-token",
        base_url="http://api:8081/bot",
        file_base_url="http://api:8081/file/bot",
        local_mode=True,
        private_chats_only=True,
        allowed_user_ids=frozenset({123}),
    )

    application = build_application(settings)

    command_handlers = [
        handler
        for handler in application.handlers[0]
        if isinstance(handler, CommandHandler)
    ]
    registered_commands = {
        command for handler in command_handlers for command in handler.commands
    }

    assert {"start", "help", "cancel"} <= registered_commands
    assert application.error_handlers
    assert any(
        isinstance(handler, CallbackQueryHandler)
        for handler in application.handlers[0]
    )
    assert application.bot.token == "test-token"
    assert application.bot.base_url.startswith("http://api:8081/bot")
    assert application.bot.base_file_url.startswith("http://api:8081/file/bot")
    assert application.bot.local_mode is True
    assert isinstance(application.bot_data["downloads"], DownloadManager)
    assert "search_engine" not in application.bot_data
    assert "search_catalog" not in application.bot_data
    callback_handlers = [
        handler
        for handler in application.handlers[0]
        if isinstance(handler, CallbackQueryHandler)
    ]
    assert len(callback_handlers) == 1


def test_quality_transfer_handler_does_not_block_cancel_updates():
    settings = BotSettings(
        token="test-token",
        base_url="http://api:8081/bot",
        file_base_url="http://api:8081/file/bot",
        local_mode=True,
        private_chats_only=True,
        allowed_user_ids=frozenset({123}),
    )

    application = build_application(settings)

    callback_handlers = [
        handler
        for handler in application.handlers[0]
        if isinstance(handler, CallbackQueryHandler)
    ]
    assert len(callback_handlers) == 1
    assert callback_handlers[0].block is False


def test_build_application_uses_configured_media_upload_timeout():
    settings = BotSettings(
        token="test-token",
        base_url="http://api:8081/bot",
        file_base_url="http://api:8081/file/bot",
        local_mode=True,
        private_chats_only=True,
        allowed_user_ids=frozenset({123}),
        upload_timeout_seconds=1800,
    )

    application = build_application(settings)

    request = application.bot.request
    assert request._media_write_timeout == 1800
    assert request._client.timeout.read == 1800


def test_error_handler_logs_safe_source_location_without_error_message(caplog):
    try:
        _raise_attribute_error()
    except AttributeError as error:
        context = type("ErrorContext", (), {"error": error})()

    with caplog.at_level(logging.ERROR, logger="qtmedia_bot.bot.application"):
        asyncio.run(handle_error(object(), context))

    assert "Unhandled Telegram update error: AttributeError" in caplog.text
    assert "test_application.py" in caplog.text
    assert "sensitive" not in caplog.text
    assert "https://secret.example/token" not in caplog.text


def test_prepare_runtime_removes_stale_media_and_expired_metadata(tmp_path):
    settings = BotSettings(
        token="test-token",
        base_url="http://api:8081/bot",
        file_base_url="http://api:8081/file/bot",
        local_mode=True,
        private_chats_only=True,
        allowed_user_ids=frozenset({123}),
        job_root=tmp_path / "jobs",
        metadata_db_path=tmp_path / "state" / "metadata.sqlite3",
        metadata_ttl_seconds=60,
        orphan_job_ttl_seconds=60,
    )
    stale_job = settings.job_root / "stale-job"
    stale_job.mkdir(parents=True)
    os.utime(stale_job, (1, 1))
    catalog = JobCatalog()
    option = QualityOption("v720", "720p", 720, 4, False, "720", "video")
    inspection = MediaInspection(
        url="https://example.com/private-source",
        title="Private title",
        duration_seconds=30,
        formats=(),
    )
    job_id = catalog.create(123, 456, inspection, (option,))
    record = catalog.claim_for_user(job_id, 123, 456, option.key)
    expired_store = JobMetadataStore(
        settings.metadata_db_path,
        retention_seconds=1,
        time_fn=lambda: 0,
    )
    expired_store.record_terminal(
        record,
        status="failed",
        temp_dir=stale_job,
        output_size=None,
        error_code="download_failed",
    )

    store = application_module.prepare_runtime(settings)

    assert store.database_path == settings.metadata_db_path
    assert not stale_job.exists()
    with sqlite3.connect(settings.metadata_db_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM telegram_job_metadata"
        ).fetchone()[0]
    assert count == 0


def test_main_loads_project_env_without_overriding_process_environment(monkeypatch):
    loaded = {}

    def fake_load_dotenv(dotenv_path, override):
        loaded["path"] = dotenv_path
        loaded["override"] = override

    class FakeApplication:
        def run_polling(self, **kwargs):
            loaded["polling"] = kwargs

    settings = BotSettings(
        token="test-token",
        base_url="http://api:8081/bot",
        file_base_url="http://api:8081/file/bot",
        local_mode=True,
        private_chats_only=True,
        allowed_user_ids=frozenset({123}),
    )
    monkeypatch.setattr(application_module, "load_dotenv", fake_load_dotenv)
    monkeypatch.setattr(application_module.BotSettings, "from_env", lambda: settings)
    def fake_build_application(value, metadata_store):
        loaded["metadata_store"] = metadata_store
        return FakeApplication()

    monkeypatch.setattr(application_module, "build_application", fake_build_application)

    application_module.main()

    assert loaded["path"] == Path(application_module.__file__).resolve().parents[3] / ".env"
    assert loaded["override"] is False
    assert loaded["metadata_store"].database_path == settings.metadata_db_path
    assert loaded["polling"]["allowed_updates"]

