"""Provider-specific URL strategies used only by the Telegram bot."""

from .adapters import adapter_for_url

__all__ = ["adapter_for_url"]
