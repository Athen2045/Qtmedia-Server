# Task 3 Report — Rich folder picker cleanup, docs, and focused regression coverage

Date: 2026-08-16

## Scope

Implemented the remaining Task 3 delta in the shared workspace after reviewing:

- `.superpowers/sdd/smartimage-folder-selection/task-3-brief.md`
- `.superpowers/sdd/smartimage-folder-selection/task-1-report.md`
- `.superpowers/sdd/smartimage-folder-selection/task-2-report.md`

Current-state review showed the earlier Task 2 integration fix had already landed
the required `chat_ui.py` behavior:

- legacy `/image PATH` and `/clear-image` command handling removed
- `select_project_image(console)` present
- Rich multi-image picker wired through `reverse_image_resolver`
- confirmation still left to the SmartImage execution path
- no automatic provider fallback introduced

That meant the remaining Task 3 work in this turn was limited to tightening
focused regression coverage and updating the README/user-facing docs.

## Files changed in this turn

- `README.md`
- `tests/test_chat_ui.py`
- this report

## TDD record

Red:

- Added a focused README regression test to `tests/test_chat_ui.py` asserting:
  - legacy `/image PATH` and `/clear-image` text are absent
  - the removed active-image-path wording is absent
  - the README documents the project `image` folder flow
  - the README mentions Kitty-optional previews
- Added a focused picker-cancel regression test covering Enter-to-cancel for the
  multi-image prompt

Focused red run:

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_chat_ui.py
```

Observed failure:

```text
FAILED tests/test_chat_ui.py::test_readme_documents_project_image_folder_and_not_legacy_commands
AssertionError: assert '/image PATH' not in ...
```

That confirmed the remaining gap was stale README documentation rather than the
already-updated UI implementation.

Green:

- Updated `README.md` to remove the legacy local command surface
- Documented `/about`, `/help`, and `/quit`
- Documented recursive project `image` folder scanning for reverse-image search
- Documented numbered Rich selection and retained confirmation behavior
- Documented Kitty-optional previews during multi-image selection
- Removed the outdated “active image path” runtime wording

Focused green run:

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_chat_ui.py
```

Result:

```text
13 passed in 0.22s
```

## Requirements checklist

- Remove legacy `/image PATH` and `/clear-image` command surface: already satisfied in current `chat_ui.py`, preserved
- Remove legacy help text: already satisfied in current `chat_ui.py`, preserved
- Ensure Rich project-image picker meets the brief: already satisfied in current `chat_ui.py`, preserved
- Ensure resolver wiring meets the brief: already satisfied in current `interactive_chat()`, preserved
- Keep confirmation after selection because SmartImage uploads externally: preserved
- Do not add automatic provider fallback: preserved
- Update README/user-facing docs: completed
- Add/update focused tests: completed
- Preserve unrelated dirty changes: completed
- Preserve SmartImage subprocess behavior: completed

## Verification

Required focused tests:

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_chat_ui.py tests/test_reverse_search_selection.py
```

Result:

```text
15 passed in 0.22s
```

Required Ruff check:

```powershell
.venv\Scripts\python.exe -m ruff check src tests main.py
```

Result:

```text
All checks passed!
```

## Self-review

- Re-read `src/private_search/app/chat_ui.py` against the Task 3 brief to confirm
  the existing picker behavior still matches the required zero/one/many/cancel
  semantics and resolver injection.
- Re-checked `tests/test_tool_registry.py` to confirm exact selected path
  propagation to confirmation and adapter execution was already covered by Task 2
  regression tests.
- Reviewed the README diff to ensure only Task 3 user-facing guidance was added
  in this turn.

## Concerns

- `README.md` already had unrelated dirty changes in the shared workspace before
  this turn. Only the Task 3 documentation hunks should be included in the
  commit; unrelated README edits should remain uncommitted.
