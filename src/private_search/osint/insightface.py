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
        settings = config.InsightFaceRuntimeSettings.from_environment()
        return cls(
            root=settings.root,
            python=settings.python,
            model_name=settings.model_name,
            image_root=settings.image_root,
            index_path=settings.index_path,
            crop_root=settings.crop_root,
            timeout_seconds=settings.timeout_seconds,
            provider_policy=settings.provider_policy,
            keep_crops=settings.keep_crops,
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
        crop_paths = self._collect_crop_paths(payload)

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
            self._worker_command(),
            request,
            cwd=config.PROJECT_ROOT,
            timeout_seconds=self.settings.timeout_seconds,
            env=environment,
        )
        if not isinstance(response, dict):
            raise TypeError("InsightFace worker returned an invalid response")
        return response

    def _worker_command(self) -> list[str]:
        return [
            str(self.settings.python.expanduser().resolve()),
            "-m",
            "private_search.osint.insightface_worker",
        ]

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

    @staticmethod
    def _collect_crop_paths(payload: dict[str, object]) -> list[Path]:
        paths: list[Path] = []
        seen: set[Path] = set()

        def remember(value: object) -> None:
            if not isinstance(value, str) or not value.strip():
                return
            resolved = Path(value).expanduser().resolve()
            if resolved in seen:
                return
            seen.add(resolved)
            paths.append(resolved)

        for value in payload.get("crops", []):
            remember(value)
        for face in payload.get("faces", []):
            if isinstance(face, dict):
                remember(face.get("crop_path"))
        for match in payload.get("local_matches", []):
            if isinstance(match, dict):
                remember(match.get("crop_path"))
        return paths


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


__all__ = ["InsightFaceAdapter", "InsightFaceSettings"]
