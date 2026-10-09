"""Structured, privacy-safe primitives for the Qtmedia desktop sidecar."""

from .download import download_media
from .inspection import inspect_url
from .models import DownloadResult, Inspection, InspectionResult, MediaLibrary
from .policy import AdapterPolicy, DesktopPolicyError

__all__ = [
    "AdapterPolicy",
    "DesktopPolicyError",
    "DownloadResult",
    "Inspection",
    "InspectionResult",
    "MediaLibrary",
    "download_media",
    "inspect_url",
]
