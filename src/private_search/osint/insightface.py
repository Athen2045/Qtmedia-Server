"""InsightFace worker adapter and face-assisted reverse-image orchestration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .. import config
from .confidence import filter_confident, normalize_score
from .worker import run_json_worker

if TYPE_CHECKING:
    from ..ai.actions import AgentAction
    from .smartimage import SmartImageAdapter


def _default_root() -> Path:
    configured = os.environ.get("PRIVATE_SEARCH_INSIGHTFACE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser()
    return config.PROJECT_ROOT / "Update" / "insightface"


def _default_python(root: Path) -> Path:
    configured = os.environ.get("PRIVATE_SEARCH_INSIGHTFACE_PYTHON", "").strip()
    if configured:
        return Path(configured).expanduser()
    return root / ".venv" / "Scripts" / "python.exe"


def _default_image_root() -> Path:
    configured = os.environ.get("PRIVATE_SEARCH_INSIGHTFACE_IMAGE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser()
    return config.PROJECT_ROOT / "image"


def _default_index_path() -> Path:
    configured = os.environ.get("PRIVATE_SEARCH_INSIGHTFACE_INDEX_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return config.FACE_INDEX_PATH


def _default_crop_root() -> Path:
    configured = os.environ.get("PRIVATE_SEARCH_INSIGHTFACE_CROP_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser()
    return config.FACE_CROP_ROOT


def _parse_keep_crops(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class InsightFaceSettings:
    """Runtime settings for the isolated InsightFace worker."""

    root: Path
    python: Path
    model_name: str = "buffalo_l"
    image_root: Path = config.PROJECT_ROOT / "image"
    index_path: Path = config.FACE_INDEX_PATH
    crop_root: Path = config.FACE_CROP_ROOT
    timeout_seconds: int = 300
    provider_policy: str = "cuda_or_cpu"
    keep_crops: bool = False

    @classmethod
    def from_environment(cls) -> InsightFaceSettings:
        root = _default_root()
        timeout = int(os.environ.get("PRIVATE_SEARCH_INSIGHTFACE_TIMEOUT", "300"))
        model_name = os.environ.get("PRIVATE_SEARCH_INSIGHTFACE_MODEL", "buffalo_l").strip()
        if not model_name:
            model_name = "buffalo_l"
        provider_policy = os.environ.get(
            "PRIVATE_SEARCH_INSIGHTFACE_PROVIDER_POLICY", "cuda_or_cpu"
        ).strip() or "cuda_or_cpu"
        return cls(
            root=root,
            python=_default_python(root),
            model_name=model_name,
            image_root=_default_image_root(),
            index_path=_default_index_path(),
            crop_root=_default_crop_root(),
            timeout_seconds=timeout,
            provider_policy=provider_policy,
            keep_crops=_parse_keep_crops(os.environ.get("PRIVATE_SEARCH_INSIGHTFACE_KEEP_CROPS")),
        )


class InsightFaceAdapter:
    """Launch the isolated worker and merge local and SmartImage matches."""

    def __init__(self, settings: InsightFaceSettings | None = None) -> None:
        self.settings = settings or InsightFaceSettings.from_environment()

    def __call__(self, action: AgentAction) -> object:
        image_path = action.image_path
        if image_path is None:
            raise ValueError("image_path is required for InsightFace reverse search")
        from .smartimage import SmartImageAdapter

        return self.analyze_and_search(Path(image_path), smartimage=SmartImageAdapter())

    def analyze_and_search(
        self,
        image_path: Path,
        *,
        smartimage: SmartImageAdapter,
    ) -> list[dict[str, object]]:
        image = Path(image_path).expanduser().resolve()
        payload = self._analyze_image(image, operation="reverse")
        results: list[dict[str, object]] = []
        crop_paths = [Path(str(path)).expanduser().resolve() for path in payload.get("crops", [])]

        try:
            results.extend(self._local_results(payload))
            results.extend(self._web_results(image, payload.get("faces", []), crop_paths, smartimage))
            return filter_confident(results, minimum=75.0)
        finally:
            if not self.settings.keep_crops:
                self._cleanup_crops(crop_paths)

    def _analyze_image(self, image_path: Path, *, operation: str) -> dict[str, object]:
        request = {
            "operation": operation,
            "image_path": str(image_path.expanduser().resolve()),
            "insightface_root": str(self.settings.root.expanduser().resolve()),
            "model_name": self.settings.model_name,
            "image_root": str(self.settings.image_root.expanduser().resolve()),
            "index_path": str(self.settings.index_path.expanduser().resolve()),
            "crop_root": str(self.settings.crop_root.expanduser().resolve()),
            "provider_policy": self.settings.provider_policy,
            "keep_crops": self.settings.keep_crops,
        }
        environment = os.environ.copy()
        existing_pythonpath = environment.get("PYTHONPATH", "")
        source_root = str(config.PROJECT_ROOT / "src")
        environment["PYTHONPATH"] = (
            source_root if not existing_pythonpath else os.pathsep.join((source_root, existing_pythonpath))
        )
        response = run_json_worker(
            [str(self.settings.python.expanduser().resolve()), str(Path(__file__).with_name("insightface_worker.py"))],
            request,
            cwd=config.PROJECT_ROOT,
            timeout_seconds=self.settings.timeout_seconds,
            env=environment,
        )
        if not isinstance(response, dict):
            raise TypeError("InsightFace worker returned an invalid response")
        return response

    @staticmethod
    def _local_results(payload: dict[str, object]) -> list[dict[str, object]]:
        provider = payload.get("provider")
        model_version = payload.get("model_version")
        results: list[dict[str, object]] = []
        for match in payload.get("local_matches", []):
            if not isinstance(match, dict):
                continue
            confidence = normalize_score(match.get("score"), source="score")
            result = {
                "kind": "local_face",
                "provider": provider,
                "model_version": model_version,
                "face_number": match.get("face_number"),
                "image_path": match.get("image_path"),
                "face_id": match.get("face_id"),
                "match_face_number": match.get("match_face_number"),
                "confidence": confidence,
            }
            results.append(result)
        return results

    @staticmethod
    def _web_results(
        image_path: Path,
        faces: object,
        crop_paths: list[Path],
        smartimage: SmartImageAdapter,
    ) -> list[dict[str, object]]:
        queued: list[tuple[Path, str, int | None]] = [(image_path, "original", None)]
        face_items = faces if isinstance(faces, list) else []
        for face in face_items:
            if not isinstance(face, dict):
                continue
            crop_path = face.get("crop_path")
            if not isinstance(crop_path, str):
                continue
            resolved = Path(crop_path).expanduser().resolve()
            if resolved not in crop_paths:
                continue
            queued.append((resolved, "face_crop", _int_or_none(face.get("face_number"))))

        seen_urls: set[str] = set()
        results: list[dict[str, object]] = []
        for path, provenance, face_number in queued:
            for row in smartimage.search_image(path):
                url = str(row.get("url", "")).strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                result = dict(row)
                result["kind"] = "web_reverse"
                result["provenance"] = provenance
                result["confidence"] = normalize_score(row.get("similarity"), source="similarity")
                if face_number is not None:
                    result["face_number"] = face_number
                results.append(result)
        return results

    @staticmethod
    def _cleanup_crops(crop_paths: list[Path]) -> None:
        for crop_path in crop_paths:
            try:
                crop_path.unlink(missing_ok=True)
            except OSError:
                continue


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


__all__ = ["InsightFaceAdapter", "InsightFaceSettings"]
