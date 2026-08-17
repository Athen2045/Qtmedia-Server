"""Optional OSINT integrations.

The exports are resolved lazily so isolated workers do not import the full
application (and its search/download dependencies) just to start.
"""

from importlib import import_module
from typing import Any

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


def __getattr__(name: str) -> Any:
    if name in {"BlackbirdAdapter", "BlackbirdExecutionError", "BlackbirdSettings"}:
        module = import_module(".blackbird", __name__)
        return getattr(module, name)
    if name in {"InsightFaceAdapter", "InsightFaceSettings"}:
        module = import_module(".insightface", __name__)
        return getattr(module, name)
    if name in {"SmartImageAdapter", "SmartImageExecutionError", "SmartImageSettings"}:
        module = import_module(".smartimage", __name__)
        return getattr(module, name)
    if name == "FaceAssistedReverseImageAdapter":
        module = import_module(".insightface", __name__)
        return module.InsightFaceAdapter
    raise AttributeError(name)
