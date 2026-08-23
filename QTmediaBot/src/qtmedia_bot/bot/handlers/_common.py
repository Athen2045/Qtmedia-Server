"""Shared handler boundary checks."""

from telegram import Update
from telegram.ext import ContextTypes

from ..access import is_private_chat, is_user_allowed
from ..config import BotSettings


def authorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return whether an update may reach a user-facing handler."""

    message = update.effective_message
    if message is None:
        return False

    chat_type = getattr(getattr(message, "chat", None), "type", None)
    user_id = getattr(getattr(update, "effective_user", None), "id", None)
    if user_id is None:
        user_id = getattr(getattr(message, "from_user", None), "id", None)
    settings = getattr(getattr(context, "application", None), "bot_data", {}).get(
        "settings"
    )
    if settings is None:
        settings = BotSettings(
            token="test",
            base_url="https://api.telegram.org/bot",
            file_base_url="https://api.telegram.org/file/bot",
            local_mode=False,
            private_chats_only=True,
            allowed_user_ids=frozenset(),
        )

    return (
        (not settings.private_chats_only or is_private_chat(chat_type))
        and is_user_allowed(user_id, settings.allowed_user_ids)
    )
