from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from private_search import config
from private_search.osint.insightface import InsightFaceAdapter, InsightFaceSettings
from private_search.osint.insightface_worker import (
    WorkerConfigurationError,
    handle_request,
)


def _install_fake_insightface_modules(
    monkeypatch: pytest.MonkeyPatch,
    *,
    providers: list[str],
    faces: list[object],
) -> None:
    onnxruntime = ModuleType("onnxruntime")
    onnxruntime.get_available_providers = lambda: list(providers)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "onnxruntime", onnxruntime)

    cv2 = ModuleType("cv2")
    cv2.imread = lambda path: SimpleNamespace(shape=(64, 48, 3), path=path)  # type: ignore[attr-defined]

    def imwrite(path: str, image: object) -> bool:
        Path(path).write_bytes(b"crop")
        return True

    cv2.imwrite = imwrite  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cv2", cv2)

    face_align = ModuleType("insightface.utils.face_align")
    face_align.norm_crop = lambda image, landmark=None: {"image": image, "landmark": landmark}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "insightface.utils.face_align", face_align)

    insightface = ModuleType("insightface")
    insightface.__version__ = "9.9.9"  # type: ignore[attr-defined]

    app_module = ModuleType("insightface.app")

    class FakeFaceAnalysis:
        def __init__(self, *, name: str, root: str, providers: list[str]):
            self.name = name
            self.root = root
            self.providers = list(providers)
            self.models = {
                "detector": SimpleNamespace(session=SimpleNamespace(_providers=list(providers)))
            }

        def prepare(self, ctx_id: int = -1, det_size: tuple[int, int] = (640, 640)) -> None:
            self.ctx_id = ctx_id
            self.det_size = det_size

        def get(self, image: object) -> list[object]:
            return list(faces)

    app_module.FaceAnalysis = FakeFaceAnalysis  # type: ignore[attr-defined]
    insightface.app = app_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "insightface", insightface)
    monkeypatch.setitem(sys.modules, "insightface.app", app_module)


def _request(tmp_path: Path, image_path: Path, **overrides: object) -> dict[str, object]:
    image_root = tmp_path / "images"
    crop_root = tmp_path / "crops"
    root = tmp_path / "insightface-root"
    root.mkdir(exist_ok=True)
    return {
        "operation": "reverse",
        "image_path": str(image_path),
        "image_root": str(image_root),
        "index_path": str(tmp_path / "face-index.sqlite"),
        "crop_root": str(crop_root),
        "insightface_root": str(root),
        "model_name": "buffalo_l",
        "provider_policy": "cuda_or_cpu",
        "keep_crops": False,
        **overrides,
    }


def test_insightface_settings_from_environment(monkeypatch, tmp_path: Path):
    root = tmp_path / "insightface"
    python = tmp_path / "worker-python.exe"
    image_root = tmp_path / "images"
    index_path = tmp_path / "face-index.sqlite"
    crop_root = tmp_path / "crops"
    for path in (root, image_root, crop_root):
        path.mkdir()
    python.write_text("", encoding="utf-8")
    monkeypatch.setenv("PRIVATE_SEARCH_INSIGHTFACE_ROOT", str(root))
    monkeypatch.setenv("PRIVATE_SEARCH_INSIGHTFACE_PYTHON", str(python))
    monkeypatch.setenv("PRIVATE_SEARCH_INSIGHTFACE_MODEL", "antelopev2")
    monkeypatch.setenv("PRIVATE_SEARCH_INSIGHTFACE_IMAGE_ROOT", str(image_root))
    monkeypatch.setenv("PRIVATE_SEARCH_INSIGHTFACE_INDEX_PATH", str(index_path))
    monkeypatch.setenv("PRIVATE_SEARCH_INSIGHTFACE_CROP_ROOT", str(crop_root))
    monkeypatch.setenv("PRIVATE_SEARCH_INSIGHTFACE_TIMEOUT", "41")
    monkeypatch.setenv("PRIVATE_SEARCH_INSIGHTFACE_PROVIDER_POLICY", "cpu")
    monkeypatch.setenv("PRIVATE_SEARCH_INSIGHTFACE_KEEP_CROPS", "1")

    settings = InsightFaceSettings.from_environment()

    assert settings.root == root
    assert settings.python == python
    assert settings.model_name == "antelopev2"
    assert settings.image_root == image_root
    assert settings.index_path == index_path
    assert settings.crop_root == crop_root
    assert settings.timeout_seconds == 41
    assert settings.provider_policy == "cpu"
    assert settings.keep_crops is True


def test_insightface_settings_default_to_isolated_worker_python(monkeypatch):
    monkeypatch.delenv("PRIVATE_SEARCH_INSIGHTFACE_ROOT", raising=False)
    monkeypatch.delenv("PRIVATE_SEARCH_INSIGHTFACE_PYTHON", raising=False)

    settings = InsightFaceSettings.from_environment()

    assert settings.python == config.PROJECT_ROOT / "Update" / "insightface" / ".venv" / "Scripts" / "python.exe"


def test_insightface_adapter_runs_json_worker(monkeypatch, tmp_path: Path):
    root = tmp_path / "insightface"
    root.mkdir()
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    image = tmp_path / "images" / "query.jpg"
    image.parent.mkdir()
    image.write_bytes(b"image")
    requests: list[dict[str, object]] = []

    def fake_run_json_worker(command, request, *, cwd, timeout_seconds, env=None):
        requests.append(request)
        assert cwd.is_dir()
        assert timeout_seconds == 9
        assert env is not None
        return {
            "provider": "CUDAExecutionProvider",
            "model_version": "9.9.9:buffalo_l",
            "faces": [],
            "local_matches": [],
            "crops": [],
        }

    monkeypatch.setattr("private_search.osint.insightface.run_json_worker", fake_run_json_worker)
    adapter = InsightFaceAdapter(
        InsightFaceSettings(
            root=root,
            python=python,
            model_name="buffalo_l",
            image_root=image.parent,
            index_path=tmp_path / "face-index.sqlite",
            crop_root=tmp_path / "crops",
            timeout_seconds=9,
        )
    )

    payload = adapter._analyze_image(image, operation="reverse")

    assert payload["provider"] == "CUDAExecutionProvider"
    assert requests == [
        {
            "operation": "reverse",
            "image_path": str(image.resolve()),
            "insightface_root": str(root.resolve()),
            "model_name": "buffalo_l",
            "image_root": str(image.parent.resolve()),
            "index_path": str((tmp_path / "face-index.sqlite").resolve()),
            "crop_root": str((tmp_path / "crops").resolve()),
            "provider_policy": "cuda_or_cpu",
            "keep_crops": False,
        }
    ]


def test_worker_reverse_reports_actual_cuda_provider_and_local_match(
    monkeypatch, tmp_path: Path
):
    image_root = tmp_path / "images"
    image_root.mkdir()
    image_path = image_root / "query.jpg"
    image_path.write_bytes(b"query")
    face = SimpleNamespace(
        bbox=[1.0, 2.0, 10.0, 12.0],
        kps=[1.0, 1.0, 3.0, 1.0, 2.0, 2.0, 1.0, 3.0, 3.0, 3.0],
        embedding=[1.0, 0.0],
        det_score=0.93,
    )
    _install_fake_insightface_modules(
        monkeypatch,
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        faces=[face],
    )

    payload = handle_request(_request(tmp_path, image_path))

    assert payload["provider"] == "CUDAExecutionProvider"
    assert payload["model_version"] == "9.9.9:buffalo_l"
    assert payload["faces"] == [
        {
            "face_number": 1,
            "bbox": [1.0, 2.0, 10.0, 12.0],
            "landmarks": [1.0, 1.0, 3.0, 1.0, 2.0, 2.0, 1.0, 3.0, 3.0, 3.0],
            "detection_score": 0.93,
            "crop_path": payload["crops"][0],
        }
    ]
    local_match = dict(payload["local_matches"][0])
    assert isinstance(local_match.pop("face_id"), str)
    assert [local_match] == [
        {
            "face_number": 1,
            "image_path": str(image_path.resolve()),
            "match_face_number": 1,
            "score": pytest.approx(1.0, abs=1e-6),
            "crop_path": payload["crops"][0],
        }
    ]
    assert Path(payload["crops"][0]).is_file()
    assert "embedding" not in repr(payload)


def test_worker_requires_explicit_cpu_fallback(monkeypatch, tmp_path: Path):
    image_root = tmp_path / "images"
    image_root.mkdir()
    image_path = image_root / "query.jpg"
    image_path.write_bytes(b"query")
    _install_fake_insightface_modules(
        monkeypatch,
        providers=["CPUExecutionProvider"],
        faces=[],
    )

    with pytest.raises(WorkerConfigurationError, match="CUDAExecutionProvider"):
        handle_request(_request(tmp_path, image_path, provider_policy="cuda"))
