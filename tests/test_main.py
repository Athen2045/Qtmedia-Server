import importlib.util
from pathlib import Path

_MAIN_SPEC = importlib.util.spec_from_file_location(
    "project_main", Path(__file__).parents[1] / "main.py"
)
main = importlib.util.module_from_spec(_MAIN_SPEC)
assert _MAIN_SPEC.loader is not None
_MAIN_SPEC.loader.exec_module(main)


def test_main_delegates_to_interactive_menu(monkeypatch):
    called = []
    monkeypatch.setattr(main, "interactive_menu", lambda: called.append(True))

    main.main()

    assert called == [True]
