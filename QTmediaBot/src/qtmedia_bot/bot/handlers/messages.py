"""Non-command message handlers for link inspection and guidance."""

from __future__ import annotations

import asyncio
import re

from telegram import Update
from telegram.ext import ContextTypes

from ..keyboards.quality import quality_menu
from ..messages import help_text
from ..services.inspection import InspectionError, inspect_source
from ..services.jobs import JobCatalog
from ..services.quality import build_quality_options
from ..services.source_policy import SourcePolicyError
from ._common import authorized

URL_PATTERN = re.compile(r"https://[^\s<>\"']+")


def _extract_url(text: str | None) -> str | None:
    if not text:
        return None
    match = URL_PATTERN.search(text)
    return match.group(0).rstrip(".,!?)]}") if match else None


def _bot_data(context: ContextTypes.DEFAULT_TYPE) -> dict[str, object]:
    return getattr(getattr(context, "application", None), "bot_data", {})


def _cancel_current_job(data: dict[str, object], user_id: int, chat_id: int) -> None:
    manager = data.get("downloads")
    if manager is not None:
        manager.cancel_for_user(user_id, chat_id)
    jobs = data.get("jobs")
    if isinstance(jobs, JobCatalog):
        current = jobs.current_for_user(user_id, chat_id)
        if current is not None:
            jobs.cancel_for_user(current.job_id, user_id, chat_id)


async def inspect_and_offer(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    user_id: int,
    chat_id: int,
) -> None:
    """Run the shared inspect-to-quality flow for a validated interaction."""

    data = _bot_data(context)
    settings = data.get("settings")
    jobs = data.get("jobs")
    if settings is None or not isinstance(jobs, JobCatalog):
        await message.reply_text(
            "Link inspection is not enabled yet.\n\n" + help_text()
        )
        return
    if jobs.current_for_user(user_id, chat_id) is not None:
        await message.reply_text(
            "You already have an active interaction. Use /cancel before starting another."
        )
        return

    inspection_message = await message.reply_text(
        "Inspecting the link for available qualities…"
    )
    inspection_message_id = getattr(inspection_message, "message_id", None)
    if not isinstance(inspection_message_id, int):
        inspection_message_id = None
    try:
        inspection = await asyncio.to_thread(inspect_source, url, settings)
        options = build_quality_options(
            {"formats": list(inspection.formats)},
            settings.max_upload_bytes,
            best_available_size_bytes=(
                inspection.best_available.size_bytes
                if inspection.best_available is not None
                else None
            ),
        )
    except SourcePolicyError:
        await message.reply_text("That link is invalid or not supported by this bot.")
        return
    except InspectionError as error:
        messages = {
            "duration_limit": "This media exceeds the bot's duration limit.",
            "playlist_not_supported": "Playlists are not supported by this bot.",
        }
        await message.reply_text(
            messages.get(error.code, "The source could not be inspected.")
        )
        return

    if not options:
        await message.reply_text("No downloadable qualities were found for this link.")
        return

    job_id = jobs.try_create(
        user_id,
        chat_id,
        inspection,
        options,
        inspection_message_id=inspection_message_id,
    )
    if job_id is None:
        await message.reply_text(
            "You already have an active interaction. Use /cancel before starting another."
        )
        return
    await message.reply_text(
        f"{inspection.title}\nChoose an available quality:",
        reply_markup=quality_menu(job_id, options),
    )


# pylint: disable=too-many-locals,too-many-return-statements
async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route download, cancellation, and direct links into short-lived flows."""

    if not authorized(update, context):
        return
    message = update.effective_message
    if message is None:
        return
    data = _bot_data(context)
    text = message.text or ""
    if text == "Download link":
        await message.reply_text("Paste a supported HTTPS media link to inspect it.")
        return
    if text == "Cancel":
        user = update.effective_user
        chat_id = getattr(getattr(message, "chat", None), "id", None)
        if user is not None and chat_id is not None:
            _cancel_current_job(data, user.id, chat_id)
        context.user_data.clear()
        await message.reply_text("The current interaction has been cancelled.")
        return

    user = update.effective_user
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    if user is None or chat_id is None:
        await message.reply_text("This message could not be associated with a chat.")
        return

    url = _extract_url(text)
    if url is not None:
        admission = data.get("admission")
        if admission is not None and not admission.allow_request(user.id):
            await message.reply_text("Too many requests. Please try again shortly.")
            return
        await inspect_and_offer(message, context, url, user.id, chat_id)
        return

    await message.reply_text("Link inspection is not enabled yet.\n\n" + help_text())
