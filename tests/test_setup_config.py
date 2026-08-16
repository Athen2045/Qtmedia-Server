from __future__ import annotations

from pathlib import Path

import pytest

from private_search import config


def test_blackbird_defaults_use_isolated_worker_root_and_python() -> None:
    settings = config.BlackbirdRuntimeSettings.from_environment({})

    assert settings.root == config.PROJECT_ROOT / "Update" / "blackbird"
    assert settings.python == settings.root / ".venv" / "Scripts" / "python.exe"
    assert settings.python != config.PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    assert settings.timeout_seconds == 300
    assert settings.threads == 8
    assert settings.update_sites is False


def test_blackbird_allows_environment_overrides() -> None:
    settings = config.BlackbirdRuntimeSettings.from_environment(
        {
            "PRIVATE_SEARCH_BLACKBIRD_ROOT": "C:/tools/blackbird",
            "PRIVATE_SEARCH_BLACKBIRD_PYTHON": "C:/tools/blackbird/python.exe",
            "PRIVATE_SEARCH_BLACKBIRD_TIMEOUT": "41",
            "PRIVATE_SEARCH_BLACKBIRD_THREADS": "6",
            "PRIVATE_SEARCH_BLACKBIRD_UPDATE_SITES": "1",
        }
    )

    assert settings.root == Path("C:/tools/blackbird")
    assert settings.python == Path("C:/tools/blackbird/python.exe")
    assert settings.timeout_seconds == 41
    assert settings.threads == 6
    assert settings.update_sites is True


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("PRIVATE_SEARCH_BLACKBIRD_TIMEOUT", "0", "at least 1 second"),
        ("PRIVATE_SEARCH_BLACKBIRD_THREADS", "0", "at least 1"),
        (
            "PRIVATE_SEARCH_BLACKBIRD_TIMEOUT",
            "abc",
            "PRIVATE_SEARCH_BLACKBIRD_TIMEOUT must be an integer value",
        ),
        (
            "PRIVATE_SEARCH_BLACKBIRD_THREADS",
            "two",
            "PRIVATE_SEARCH_BLACKBIRD_THREADS must be an integer value",
        ),
    ],
)
def test_blackbird_rejects_invalid_numeric_settings(
    name: str, value: str, message: str
) -> None:
    with pytest.raises(config.ConfigurationError, match=message):
        config.BlackbirdRuntimeSettings.from_environment({name: value})


def test_insightface_defaults_use_local_paths() -> None:
    settings = config.InsightFaceRuntimeSettings.from_environment({})

    assert settings.root == config.PROJECT_ROOT / "Update" / "insightface"
    assert settings.python == settings.root / ".venv" / "Scripts" / "python.exe"
    assert settings.image_root == config.PROJECT_ROOT / "image"
    assert settings.index_path == config.FACE_INDEX_PATH
    assert settings.crop_root == config.FACE_CROP_ROOT
    assert settings.model_name == "buffalo_l"
    assert settings.timeout_seconds == 300
    assert settings.provider_policy == "cuda_or_cpu"
    assert settings.keep_crops is False


def test_insightface_allows_environment_overrides() -> None:
    settings = config.InsightFaceRuntimeSettings.from_environment(
        {
            "PRIVATE_SEARCH_INSIGHTFACE_ROOT": "C:/tools/insightface",
            "PRIVATE_SEARCH_INSIGHTFACE_PYTHON": "C:/tools/insightface/python.exe",
            "PRIVATE_SEARCH_INSIGHTFACE_MODEL": "antelopev2",
            "PRIVATE_SEARCH_INSIGHTFACE_IMAGE_ROOT": "C:/cases/images",
            "PRIVATE_SEARCH_INSIGHTFACE_INDEX_PATH": "C:/cases/index.sqlite",
            "PRIVATE_SEARCH_INSIGHTFACE_CROP_ROOT": "C:/cases/crops",
            "PRIVATE_SEARCH_INSIGHTFACE_TIMEOUT": "41",
            "PRIVATE_SEARCH_INSIGHTFACE_PROVIDER_POLICY": "cpu",
            "PRIVATE_SEARCH_INSIGHTFACE_KEEP_CROPS": "true",
        }
    )

    assert settings.root == Path("C:/tools/insightface")
    assert settings.python == Path("C:/tools/insightface/python.exe")
    assert settings.model_name == "antelopev2"
    assert settings.image_root == Path("C:/cases/images")
    assert settings.index_path == Path("C:/cases/index.sqlite")
    assert settings.crop_root == Path("C:/cases/crops")
    assert settings.timeout_seconds == 41
    assert settings.provider_policy == "cpu"
    assert settings.keep_crops is True


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("PRIVATE_SEARCH_INSIGHTFACE_TIMEOUT", "0", "at least 1 second"),
        (
            "PRIVATE_SEARCH_INSIGHTFACE_TIMEOUT",
            "abc",
            "PRIVATE_SEARCH_INSIGHTFACE_TIMEOUT must be an integer value",
        ),
        (
            "PRIVATE_SEARCH_INSIGHTFACE_PROVIDER_POLICY",
            "gpu",
            "must be one of: cpu, cuda, cuda_or_cpu",
        ),
    ],
)
def test_insightface_rejects_invalid_settings(
    name: str, value: str, message: str
) -> None:
    with pytest.raises(config.ConfigurationError, match=message):
        config.InsightFaceRuntimeSettings.from_environment({name: value})


def test_runtime_directories_include_face_index_parent() -> None:
    directories = config.runtime_directories()

    assert config.DOWNLOAD_ROOT in directories
    assert config.CACHE_ROOT in directories
    assert config.FACE_CROP_ROOT in directories
    assert config.FACE_INDEX_PATH.parent in directories
