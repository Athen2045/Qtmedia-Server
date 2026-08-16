"""Optional OSINT integrations."""

from .blackbird import (
    BlackbirdAdapter,
    BlackbirdExecutionError,
    BlackbirdSettings,
)
from .insightface import InsightFaceAdapter, InsightFaceSettings
from .smartimage import SmartImageAdapter, SmartImageExecutionError, SmartImageSettings

FaceAssistedReverseImageAdapter = InsightFaceAdapter

__all__ = [
    "BlackbirdAdapter",
    "BlackbirdExecutionError",
    "BlackbirdSettings",
    "FaceAssistedReverseImageAdapter",
    "InsightFaceAdapter",
    "InsightFaceSettings",
    "SmartImageAdapter",
    "SmartImageExecutionError",
    "SmartImageSettings",
]
