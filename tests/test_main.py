import importlib.util
from pathlib import Path

import private_search.osint as osint_module

_MAIN_SPEC = importlib.util.spec_from_file_location(
    "project_main", Path(__file__).parents[1] / "main.py"
)
main = importlib.util.module_from_spec(_MAIN_SPEC)
assert _MAIN_SPEC.loader is not None
_MAIN_SPEC.loader.exec_module(main)


def test_main_delegates_to_interactive_chat(monkeypatch):
    called = []
    monkeypatch.setattr(main, "interactive_chat", lambda: called.append(True))

    main.main()

    assert called == [True]


def test_osint_exports_face_assisted_reverse_search_without_legacy_runtime():
    legacy_prefix = bytes((84, 111, 111, 107, 105, 101)).decode()

    assert osint_module.FaceAssistedReverseImageAdapter is osint_module.InsightFaceAdapter
    assert all(not name.startswith(legacy_prefix) for name in osint_module.__all__)
