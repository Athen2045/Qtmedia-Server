"""Pure access-control checks for Telegram updates."""


def is_private_chat(chat_type: str | None) -> bool:
    """Return whether a Telegram chat type is a private chat."""

    return chat_type == "private"


def is_user_allowed(
    user_id: int | None, allowed_user_ids: frozenset[int]
) -> bool:
    """Apply an optional allowlist without logging user-identifying data."""

    if user_id is None:
        return False
    return not allowed_user_ids or user_id in allowed_user_ids
