"""Optional OSINT integrations."""

from .blackbird import (
    BlackbirdAdapter,
    BlackbirdExecutionError,
    BlackbirdSettings,
)
from .smartimage import SmartImageAdapter, SmartImageExecutionError, SmartImageSettings
from .tookie import TookieAdapter, TookieExecutionError, TookieSettings

__all__ = [
    "BlackbirdAdapter",
    "BlackbirdExecutionError",
    "BlackbirdSettings",
    "SmartImageAdapter",
    "SmartImageExecutionError",
    "SmartImageSettings",
    "TookieAdapter",
    "TookieExecutionError",
    "TookieSettings",
]
