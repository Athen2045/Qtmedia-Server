"""Reply keyboard builders for the initial bot menu."""

from telegram import KeyboardButton, ReplyKeyboardMarkup


def main_menu() -> ReplyKeyboardMarkup:
    """Return the initial actions without exposing quality choices early."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("Download link")],
            [KeyboardButton("Cancel")],
        ],
        resize_keyboard=True,
    )
