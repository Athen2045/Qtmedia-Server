"""Stable, privacy-aware user-facing bot messages."""


def welcome_text() -> str:
    """Return the onboarding message shown by ``/start``."""

    return (
        "Paste a supported media link to inspect and download it.\n\n"
        "Media is processed temporarily and deleted from this service after "
        "delivery or expiry.\n"
        "Please download only content you are allowed to access and redistribute."
    )


def help_text() -> str:
    """Return the concise command and workflow guide."""

    return (
        "Use Download link or paste a supported media link directly.\n"
        "The bot will show only qualities available from the source.\n"
        "Use /cancel to clear the current interaction."
    )


def cancel_text() -> str:
    """Return the cancellation acknowledgement."""

    return "The current interaction has been cancelled."
