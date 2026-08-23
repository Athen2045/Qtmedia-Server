"""Inline quality keyboard builders."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..services.quality import QualityOption, format_size


def quality_menu(
    job_id: str, options: tuple[QualityOption, ...]
) -> InlineKeyboardMarkup:
    """Build one opaque callback button per available quality."""

    rows = [
        [
            InlineKeyboardButton(
                text=f"{option.label} — {format_size(option.size_bytes, option.size_approximate)}",
                callback_data=f"quality:{job_id}:{option.key}",
            )
        ]
        for option in options
    ]
    return InlineKeyboardMarkup(rows)
