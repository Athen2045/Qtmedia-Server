"""Telegram application construction and polling entrypoint."""

from __future__ import annotations

import logging
import traceback
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import BotSettings
from .handlers.callbacks import quality_selected
from .handlers.commands import cancel, help_command, start
from .handlers.messages import text_message
from .logging_utils import configure_private_logging
from .services.admission import AdmissionController
from .services.delivery import TelegramDeliveryTransport
from .services.downloads import DownloadManager, cleanup_orphaned_job_directories
from .services.jobs import JobCatalog
from .storage import JobMetadataStore

logger = logging.getLogger(__name__)


async def _resume_retained_cleanups(application: Application) -> None:
    """Restart expiry timers for ambiguous path-based uploads."""

    application.bot_data["downloads"].resume_retained_cleanups()


def _load_project_environment() -> None:
    """Load the ignored project-root .env without overriding shell values."""

    project_root = Path(__file__).resolve().parents[3]
    load_dotenv(project_root / ".env", override=False)


def _safe_error_location(error: BaseException | None) -> str:
    """Return traceback location without including exception data."""

    if error is None or error.__traceback__ is None:
        return "unknown"
    frame = traceback.extract_tb(error.__traceback__)[-1]
    return f"{Path(frame.filename).name}:{frame.lineno} ({frame.name})"


async def handle_error(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Log an error class without recording user content or credentials."""

    del update
    error = context.error
    logger.error(
        "Unhandled Telegram update error: %s at %s",
        type(error).__name__ if error is not None else "UnknownError",
        _safe_error_location(error),
    )


def prepare_runtime(settings: BotSettings) -> JobMetadataStore:
    """Initialize short-lived state and remove abandoned job directories."""

    metadata_store = JobMetadataStore(
        settings.metadata_db_path,
        retention_seconds=settings.metadata_ttl_seconds,
    )
    metadata_store.initialize()
    metadata_store.purge_expired()
    cleanup_orphaned_job_directories(
        settings.job_root,
        max_age_seconds=settings.orphan_job_ttl_seconds,
        unconfirmed_max_age_seconds=(
            settings.unconfirmed_upload_retention_seconds
        ),
    )
    return metadata_store


def build_application(
    settings: BotSettings, metadata_store: JobMetadataStore | None = None
) -> Application:
    """Build, configure, and register handlers without starting the network loop."""

    delivery = TelegramDeliveryTransport(
        local_mode=settings.local_mode,
        timeout_seconds=settings.upload_timeout_seconds,
    )
    application = (
        ApplicationBuilder()
        .token(settings.token)
        .base_url(settings.base_url)
        .base_file_url(settings.file_base_url)
        .local_mode(settings.local_mode)
        .request(delivery.request)
        .post_init(_resume_retained_cleanups)
        .build()
    )
    application.bot_data["settings"] = settings
    jobs = JobCatalog(ttl_seconds=settings.job_ttl_seconds)
    application.bot_data["jobs"] = jobs
    admission = AdmissionController(
        max_requests=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
        max_queued_jobs=settings.max_queued_jobs,
    )
    application.bot_data["admission"] = admission
    application.bot_data["downloads"] = DownloadManager(
        jobs,
        settings,
        metadata_store,
        delivery=delivery,
        admission=admission,
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_message)
    )
    application.add_handler(
        CallbackQueryHandler(
            quality_selected,
            pattern=r"^quality:",
            block=False,
        )
    )
    application.add_error_handler(handle_error)
    return application


def main() -> None:
    """Load environment settings and run the polling application."""

    _load_project_environment()
    settings = BotSettings.from_env()
    configure_private_logging((settings.token,))
    metadata_store = prepare_runtime(settings)
    application = build_application(settings, metadata_store)
    application.run_polling(allowed_updates=Update.ALL_TYPES)
