"""Command handlers for the Telegram bot skeleton."""

from telegram import Update
from telegram.ext import ContextTypes

from ..keyboards.main import main_menu
from ..messages import cancel_text, help_text, welcome_text
from ..services.jobs import JobCatalog
from ._common import authorized


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show onboarding guidance to an authorized private-chat user."""

    if not authorized(update, context):
        return
    message = update.effective_message
    if message is not None:
        await message.reply_text(welcome_text(), reply_markup=main_menu())


async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show the initial workflow guide."""

    if not authorized(update, context):
        return
    message = update.effective_message
    if message is not None:
        await message.reply_text(help_text(), reply_markup=main_menu())


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear the current interaction state and acknowledge cancellation."""

    if not authorized(update, context):
        return
    message = update.effective_message
    user = update.effective_user
    manager = getattr(getattr(context, "application", None), "bot_data", {}).get(
        "downloads"
    )
    if (
        manager is not None
        and message is not None
        and user is not None
        and getattr(getattr(message, "chat", None), "id", None) is not None
    ):
        manager.cancel_for_user(user.id, message.chat.id)
    jobs = getattr(getattr(context, "application", None), "bot_data", {}).get("jobs")
    if (
        isinstance(jobs, JobCatalog)
        and user is not None
        and message is not None
        and getattr(getattr(message, "chat", None), "id", None) is not None
    ):
        current = jobs.current_for_user(user.id, message.chat.id)
        if current is not None:
            jobs.cancel_for_user(current.job_id, user.id, message.chat.id)
    context.user_data.clear()
    if message is not None:
        await message.reply_text(cancel_text(), reply_markup=main_menu())
