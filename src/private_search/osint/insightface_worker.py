"""Isolated InsightFace worker for local face indexing and reverse search."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import uuid
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # pragma: no branch - one import path succeeds depending on launch mode
    from .face_store import FaceIndex, FaceRecord, ImageRecord
except ImportError:  # pragma: no cover - exercised by script-launch regression test
    from private_search.osint.face_store import FaceIndex, FaceRecord, ImageRecord

_SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_CUDA_DLL_HANDLES: list[object] = []


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
    response = {
        "provider": actual_provider,
        "model_version": version,
        "faces": [],
        "local_matches": [],
        "crops": [],
    }
    created_crops: list[Path] = []
    retained_crops: set[Path] = set()
    try:
        with FaceIndex(settings.index_path) as index:
            if settings.operation in {"refresh", "reverse"}:
                image_records = tuple(_discover_images(settings.image_root))
                report = index.refresh_images(image_records, model_version=version)
                for image_record in report.pending_images:
                    indexed_faces = _extract_faces(
                        analysis,
                        image_record.path,
                        settings.crop_root,
                        write_crops=settings.keep_crops,
                        created_crops=created_crops,
                    )
                    index.upsert_faces(image_record, indexed_faces)

            query_faces: list[FaceRecord] = []
            if settings.operation in {"analyze", "reverse"}:
                query_faces = _extract_faces(
                    analysis,
                    settings.image_path,
                    settings.crop_root,
                    write_crops=True,
                    created_crops=created_crops,
                )
                response["faces"] = [_face_payload(face) for face in query_faces]
                response["crops"] = [
                    str(face.crop_path.resolve())
                    for face in query_faces
                    if face.crop_path is not None and face.crop_path.exists()
                ]
                retained_crops = {
                    face.crop_path.resolve()
                    for face in query_faces
                    if face.crop_path is not None
                }

            if settings.operation == "reverse":
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
                response["local_matches"] = local_matches
        return response
    finally:
        if not settings.keep_crops:
            _cleanup_crops(path for path in created_crops if path.resolve() not in retained_crops)


def main() -> int:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise TypeError("request must be a JSON object")
        # InsightFace prints model-loading diagnostics; keep stdout reserved for
        # the worker's single machine-readable JSON response.
        with redirect_stdout(sys.stderr):
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
    image_root = _require_directory(request.get("image_root"), field="image_root")
    image_path = _require_supported_image_file(
        request.get("image_path"),
        field="image_path",
        image_root=image_root,
    )
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
    _prepare_cuda_runtime()
    import onnxruntime  # type: ignore[import-not-found]

    return list(onnxruntime.get_available_providers())


def _prepare_cuda_runtime() -> None:
    """Expose pip-installed CUDA DLLs to Windows before ORT creates sessions."""

    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    candidates = (
        site_packages / "nvidia" / "cu13" / "bin" / "x86_64",
        site_packages / "nvidia" / "cudnn" / "bin",
        site_packages / "nvidia" / "cufft" / "bin",
        site_packages / "nvidia" / "nvjitlink" / "bin",
    )
    existing = [path for path in candidates if path.is_dir()]
    if not existing:
        return
    os.environ["PATH"] = os.pathsep.join([*(str(path) for path in existing), os.environ.get("PATH", "")])
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is None:
        return
    for path in existing:
        try:
            _CUDA_DLL_HANDLES.append(add_dll_directory(str(path)))
        except OSError:
            continue


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
    _prepare_cuda_runtime()
    import insightface  # type: ignore[import-not-found]
    from insightface.app import FaceAnalysis  # type: ignore[import-not-found]

    analysis_kwargs = {
        "name": model_name,
        "root": str(insightface_root),
        "providers": providers,
        "allowed_modules": ["detection", "recognition"],
    }
    try:
        analysis = FaceAnalysis(**analysis_kwargs)
    except TypeError as error:
        if "allowed_modules" not in str(error):
            raise
        # Keep compatibility with lightweight test doubles and older packages.
        analysis_kwargs.pop("allowed_modules")
        analysis = FaceAnalysis(**analysis_kwargs)
    analysis.prepare(ctx_id=0 if providers[0] == "CUDAExecutionProvider" else -1, det_size=(640, 640))
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
        if not _is_regular_file(path) or path.suffix.casefold() not in _SUPPORTED_IMAGE_SUFFIXES:
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


def _extract_faces(
    analysis: object,
    image_path: Path,
    crop_root: Path,
    *,
    write_crops: bool,
    created_crops: list[Path],
) -> list[FaceRecord]:
    import cv2  # type: ignore[import-not-found]

    if write_crops:
        from insightface.utils.face_align import (
            norm_crop,  # type: ignore[import-not-found]
        )

    image = cv2.imread(str(image_path))
    if image is None:
        raise WorkerConfigurationError(f"image is not decodable: {image_path}")
    detected = analysis.get(image)
    faces: list[FaceRecord] = []
    image_stem = image_path.stem
    for number, detected_face in enumerate(detected, start=1):
        bbox = [float(value) for value in list(_get_required_sequence(detected_face, "bbox"))]
        landmarks = [
            float(value)
            for point in _get_required_sequence(detected_face, "kps")
            for value in (point if isinstance(point, (list, tuple)) else [point])
        ]
        embedding = [float(value) for value in list(_get_required_sequence(detected_face, "embedding"))]
        detection_score = float(detected_face.det_score)
        crop_path: Path | None = None
        if write_crops:
            landmark_input: object = landmarks
            try:
                import numpy as np  # type: ignore[import-not-found]

                landmark_input = np.asarray(landmarks, dtype=np.float32).reshape(5, 2)
            except ModuleNotFoundError:
                pass
            crop_image = norm_crop(image, landmark=landmark_input)
            crop_path = (crop_root / f"{image_stem}-face-{number}.jpg").resolve()
            if not cv2.imwrite(str(crop_path), crop_image):
                raise WorkerConfigurationError(f"failed to write face crop: {crop_path}")
            created_crops.append(crop_path)
        faces.append(
            FaceRecord(
                face_id=f"{image_path.resolve().as_posix()}#{uuid.uuid4().hex}",
                face_number=number,
                bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
                landmarks=tuple(landmarks),
                embedding=tuple(embedding),
                detection_score=detection_score,
                crop_path=crop_path,
            )
        )
    return faces


def _face_payload(face: FaceRecord) -> dict[str, object]:
    return {
        "face_number": face.face_number,
        "bbox": list(face.bbox),
        "landmarks": list(face.landmarks),
        "detection_score": face.detection_score,
        "crop_path": str(face.crop_path.resolve()) if face.crop_path is not None else None,
    }


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
    if not _is_regular_file(path):
        raise WorkerConfigurationError(f"{field} must point to an existing file")
    return path


def _require_supported_image_file(value: object, *, field: str, image_root: Path) -> Path:
    path = _require_existing_file(value, field=field)
    if path.suffix.casefold() not in _SUPPORTED_IMAGE_SUFFIXES:
        raise WorkerConfigurationError(f"{field} must point to a supported image file")
    try:
        path.relative_to(image_root)
    except ValueError as error:
        raise WorkerConfigurationError(f"{field} must be inside image_root") from error
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


def _is_regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.stat().st_mode)
    except OSError:
        return False


def _cleanup_crops(paths: Any) -> None:
    for crop_path in paths:
        try:
            Path(crop_path).unlink(missing_ok=True)
        except OSError:
            continue


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess worker tests
    raise SystemExit(main())
