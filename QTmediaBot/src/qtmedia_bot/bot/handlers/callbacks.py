"""Authorized inline callback handlers for quality choices."""

import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..services.downloads import DownloadCancelled, DownloadError
from ..services.jobs import JobCatalog
from ..services.progress import TelegramProgressReporter
from ..services.source_policy import SourcePolicyError
from ._common import authorized

logger = logging.getLogger(__name__)


async def _delete_transient_status_messages(
    context: ContextTypes.DEFAULT_TYPE, record, selected_message
) -> None:
    """Remove transient bot statuses after Telegram confirms media delivery."""

    bot = getattr(context, "bot", None)
    if bot is None:
        bot = getattr(getattr(context, "application", None), "bot", None)
    if bot is None:
        return
    message_ids = tuple(
        dict.fromkeys(
            message_id
            for message_id in (
                record.inspection_message_id,
                getattr(selected_message, "message_id", None),
            )
            if isinstance(message_id, int)
        )
    )
    for message_id in message_ids:
        try:
            await bot.delete_message(chat_id=record.chat_id, message_id=message_id)
        except TelegramError as error:
            logger.debug(
                "Could not delete transient status message: %s",
                type(error).__name__,
            )


# pylint: disable=too-many-branches,too-many-locals,too-many-return-statements
async def quality_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Validate a quality callback without starting the download stage yet."""

    query = update.callback_query
    if query is None:
        return
    if not authorized(update, context):
        await query.answer("You are not authorized to use this selection.", show_alert=True)
        return

    data = query.data or ""
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "quality":
        await query.answer("This selection has expired.", show_alert=True)
        return

    jobs = getattr(getattr(context, "application", None), "bot_data", {}).get("jobs")
    if not isinstance(jobs, JobCatalog):
        await query.answer("This selection has expired.", show_alert=True)
        return

    message = query.message
    user = update.effective_user
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    if message is None or user is None or chat_id is None:
        await query.answer("This selection has expired.", show_alert=True)
        return
    record = jobs.get_for_user(parts[1], user.id, chat_id)
    if record is None:
        await query.answer("This selection has expired.", show_alert=True)
        return
    option = next((item for item in record.options if item.key == parts[2]), None)
    if option is None:
        await query.answer("This quality is no longer available.", show_alert=True)
        return

    claimed = jobs.claim_for_user(parts[1], user.id, chat_id, option.key)
    bot_data = getattr(getattr(context, "application", None), "bot_data", {})
    manager = bot_data.get("downloads")
    settings = bot_data.get("settings")
    if claimed is None or manager is None or settings is None:
        await query.answer("This selection has expired.", show_alert=True)
        return

    admission = bot_data.get("admission")
    if admission is not None and not admission.try_enter_queue(claimed.job_id):
        jobs.cancel_for_user(claimed.job_id, user.id, chat_id)
        await query.answer("The bot is busy. Please try again shortly.", show_alert=True)
        return

    await query.answer("Download started.")
    reporter = TelegramProgressReporter(
        query.edit_message_text,
        label=option.label,
        update_interval_seconds=settings.progress_update_seconds,
    )
    try:
        await manager.run(claimed, option, message, reporter)
    except DownloadCancelled:
        await query.edit_message_text("The download was cancelled.")
    except SourcePolicyError:
        await query.edit_message_text("That link is invalid or no longer supported.")
    except DownloadError as error:
        messages = {
            "disk_space": "There is not enough free disk space for this download.",
            "output_limit": "The downloaded file exceeds the bot's size limit.",
            "download_timeout": "The download timed out. Please try again.",
            "upload_timeout": "The Telegram upload timed out. Please try again.",
            "upload_failed": "Telegram could not receive the file. Please try again.",
            "upload_unconfirmed": (
                "Telegram did not confirm the upload. The file may still appear "
                "shortly; no duplicate retry was made."
            ),
        }
        await query.edit_message_text(
            messages.get(error.code, "The media could not be downloaded.")
        )
    else:
        await _delete_transient_status_messages(context, claimed, message)
