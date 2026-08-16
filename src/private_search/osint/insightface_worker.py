"""Isolated InsightFace worker for local face indexing and reverse search."""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .face_store import FaceIndex, FaceRecord, ImageRecord

_SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class WorkerConfigurationError(RuntimeError):
    """Raised when the worker cannot satisfy the requested provider policy."""


@dataclass(frozen=True)
class _Settings:
    operation: str
    image_path: Path
    image_root: Path
    index_path: Path
    crop_root: Path
    insightface_root: Path
    model_name: str
    provider_policy: str
    keep_crops: bool


def handle_request(request: dict[str, object]) -> dict[str, object]:
    settings = _parse_request(request)
    available_providers = _available_providers()
    requested_providers = _requested_providers(settings.provider_policy, available_providers)
    analysis, actual_provider, version = _create_analysis(
        settings.insightface_root,
        settings.model_name,
        requested_providers,
    )

    settings.crop_root.mkdir(parents=True, exist_ok=True)
    image_records = tuple(_discover_images(settings.image_root))
    with FaceIndex(settings.index_path) as index:
        report = index.refresh_images(image_records, model_version=version)
        for image_record in report.pending_images:
            indexed_faces = _extract_faces(analysis, image_record.path, settings.crop_root)
            index.upsert_faces(image_record, indexed_faces)

        query_faces = _extract_faces(analysis, settings.image_path, settings.crop_root)
        local_matches: list[dict[str, object]] = []
        for face in query_faces:
            for match in index.search(face.embedding, limit=10):
                local_matches.append(
                    {
                        "face_number": face.face_number,
                        "image_path": str(match.image_path.resolve()),
                        "face_id": match.face_id,
                        "match_face_number": match.face_number,
                        "score": match.score,
                        "crop_path": str(face.crop_path.resolve()) if face.crop_path is not None else None,
                    }
                )

    return {
        "provider": actual_provider,
        "model_version": version,
        "faces": [
            {
                "face_number": face.face_number,
                "bbox": list(face.bbox),
                "landmarks": list(face.landmarks),
                "detection_score": face.detection_score,
                "crop_path": str(face.crop_path.resolve()) if face.crop_path is not None else None,
            }
            for face in query_faces
        ],
        "local_matches": local_matches,
        "crops": [
            str(face.crop_path.resolve())
            for face in query_faces
            if face.crop_path is not None and face.crop_path.exists()
        ],
    }


def main() -> int:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise TypeError("request must be a JSON object")
        response = handle_request(request)
    except (OSError, TypeError, ValueError, WorkerConfigurationError) as error:  # pragma: no cover
        print(str(error), file=sys.stderr)
        return 1
    json.dump(response, sys.stdout)
    return 0


def _parse_request(request: dict[str, object]) -> _Settings:
    operation = _require_text(request.get("operation"), field="operation")
    if operation not in {"analyze", "refresh", "reverse"}:
        raise WorkerConfigurationError("operation must be analyze, refresh, or reverse")
    image_path = _require_existing_file(request.get("image_path"), field="image_path")
    image_root = _require_directory(request.get("image_root"), field="image_root")
    index_path = _require_path(request.get("index_path"), field="index_path")
    crop_root = _require_path(request.get("crop_root"), field="crop_root")
    insightface_root = _require_directory(
        request.get("insightface_root"),
        field="insightface_root",
        create=True,
    )
    model_name = _require_text(request.get("model_name"), field="model_name")
    provider_policy = _require_text(request.get("provider_policy"), field="provider_policy")
    keep_crops = bool(request.get("keep_crops"))
    return _Settings(
        operation=operation,
        image_path=image_path,
        image_root=image_root,
        index_path=index_path,
        crop_root=crop_root,
        insightface_root=insightface_root,
        model_name=model_name,
        provider_policy=provider_policy,
        keep_crops=keep_crops,
    )


def _available_providers() -> list[str]:
    import onnxruntime  # type: ignore[import-not-found]

    return list(onnxruntime.get_available_providers())


def _requested_providers(policy: str, available_providers: list[str]) -> list[str]:
    normalized = policy.strip().casefold()
    if normalized == "cuda":
        if "CUDAExecutionProvider" not in available_providers:
            raise WorkerConfigurationError(
                "CUDAExecutionProvider is unavailable and provider_policy=cuda forbids CPU fallback"
            )
        return ["CUDAExecutionProvider"]
    if normalized == "cpu":
        if "CPUExecutionProvider" not in available_providers:
            raise WorkerConfigurationError("CPUExecutionProvider is unavailable")
        return ["CPUExecutionProvider"]
    if normalized == "cuda_or_cpu":
        providers: list[str] = []
        if "CUDAExecutionProvider" in available_providers:
            providers.append("CUDAExecutionProvider")
        if "CPUExecutionProvider" in available_providers:
            providers.append("CPUExecutionProvider")
        if not providers:
            raise WorkerConfigurationError("no supported ONNX Runtime providers are available")
        return providers
    raise WorkerConfigurationError("provider_policy must be cuda, cpu, or cuda_or_cpu")


def _create_analysis(insightface_root: Path, model_name: str, providers: list[str]):
    import insightface  # type: ignore[import-not-found]
    from insightface.app import FaceAnalysis  # type: ignore[import-not-found]

    analysis = FaceAnalysis(name=model_name, root=str(insightface_root), providers=providers)
    analysis.prepare(ctx_id=-1, det_size=(640, 640))
    actual_provider = _active_provider(analysis)
    if actual_provider is None:
        raise WorkerConfigurationError("could not determine the active ONNX Runtime provider")
    if (
        providers[0] == "CUDAExecutionProvider"
        and actual_provider != "CUDAExecutionProvider"
        and len(providers) == 1
    ):
        raise WorkerConfigurationError(
            "CUDAExecutionProvider was requested explicitly but the active provider is different"
        )
    version = f"{getattr(insightface, '__version__', 'unknown')}:{model_name}"
    return analysis, actual_provider, version


def _active_provider(analysis: object) -> str | None:
    models = getattr(analysis, "models", None)
    if isinstance(models, dict):
        for model in models.values():
            session = getattr(model, "session", None)
            providers = getattr(session, "_providers", None)
            if isinstance(providers, list) and providers:
                return str(providers[0])
            providers = getattr(session, "get_providers", None)
            if callable(providers):
                active = providers()
                if active:
                    return str(active[0])
    configured = getattr(analysis, "providers", None)
    if isinstance(configured, list) and configured:
        return str(configured[0])
    return None


def _discover_images(image_root: Path) -> list[ImageRecord]:
    images: list[ImageRecord] = []
    for path in sorted(image_root.rglob("*")):
        if not path.is_file() or path.suffix.casefold() not in _SUPPORTED_IMAGE_SUFFIXES:
            continue
        images.append(_build_image_record(path))
    return images


def _build_image_record(path: Path) -> ImageRecord:
    stat = path.stat()
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    shape = _image_shape(path)
    return ImageRecord(
        path=path.resolve(),
        content_hash=content_hash,
        file_size=stat.st_size,
        modified_at_ns=stat.st_mtime_ns,
        width=shape[1],
        height=shape[0],
    )


def _image_shape(path: Path) -> tuple[int, int]:
    import cv2  # type: ignore[import-not-found]

    image = cv2.imread(str(path))
    if image is None or not hasattr(image, "shape"):
        raise WorkerConfigurationError(f"image is not decodable: {path}")
    shape = image.shape
    if len(shape) < 2:
        raise WorkerConfigurationError(f"image has an invalid shape: {path}")
    return int(shape[0]), int(shape[1])


def _extract_faces(analysis: object, image_path: Path, crop_root: Path) -> list[FaceRecord]:
    import cv2  # type: ignore[import-not-found]
    from insightface.utils.face_align import norm_crop  # type: ignore[import-not-found]

    image = cv2.imread(str(image_path))
    if image is None:
        raise WorkerConfigurationError(f"image is not decodable: {image_path}")
    detected = analysis.get(image)
    faces: list[FaceRecord] = []
    image_stem = image_path.stem
    for number, detected_face in enumerate(detected, start=1):
        bbox = [float(value) for value in list(_get_required_sequence(detected_face, "bbox"))]
        landmarks = [float(value) for value in list(_get_required_sequence(detected_face, "kps"))]
        embedding = [float(value) for value in list(_get_required_sequence(detected_face, "embedding"))]
        detection_score = float(detected_face.det_score)
        crop_image = norm_crop(image, landmark=landmarks)
        crop_path = crop_root / f"{image_stem}-face-{number}.jpg"
        if not cv2.imwrite(str(crop_path), crop_image):
            raise WorkerConfigurationError(f"failed to write face crop: {crop_path}")
        faces.append(
            FaceRecord(
                face_id=f"{image_path.resolve().as_posix()}#{uuid.uuid4().hex}",
                face_number=number,
                bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
                landmarks=tuple(landmarks),
                embedding=tuple(embedding),
                detection_score=detection_score,
                crop_path=crop_path.resolve(),
            )
        )
    return faces


def _get_required_sequence(face: object, field: str) -> list[Any]:
    value = getattr(face, field, None)
    if value is None:
        raise WorkerConfigurationError(f"detected face is missing {field}")
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        raise WorkerConfigurationError(f"detected face {field} must be a sequence")
    return list(value)


def _require_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkerConfigurationError(f"{field} must be a non-empty string")
    return value.strip()


def _require_existing_file(value: object, *, field: str) -> Path:
    path = _require_path(value, field=field)
    if not path.is_file():
        raise WorkerConfigurationError(f"{field} must point to an existing file")
    return path


def _require_directory(value: object, *, field: str, create: bool = False) -> Path:
    path = _require_path(value, field=field)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise WorkerConfigurationError(f"{field} must point to a directory")
    return path


def _require_path(value: object, *, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise WorkerConfigurationError(f"{field} must be a non-empty path")
    return Path(value).expanduser().resolve()


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess worker tests
    raise SystemExit(main())
