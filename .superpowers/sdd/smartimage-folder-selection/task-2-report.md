# Task 2 Report — deterministic reverse-search resolution before confirmation

Date: 2026-08-16

## Scope

Implemented Task 2 in the shared workspace using only the requested Task 2 files:

- `src/private_search/ai/actions.py`
- `src/private_search/ai/chat.py`
- `src/private_search/ai/tools.py`
- `tests/test_reverse_search_selection.py`
- `tests/test_agent_actions.py`
- `tests/test_chat.py`
- `tests/test_tool_registry.py`

I preserved unrelated dirty workspace changes and did not modify the Task 1 UI files.

## TDD record

Red:

- Added failing coverage for reverse-search keyword detection.
- Added failing coverage for `reverse_image_search` with `image_path: null`.
- Replaced the old active-image chat expectation with deterministic reverse-search forcing.
- Added failing coverage for resolver-before-confirmation behavior in `ToolRegistry`.

First focused test run:

```text
=================================== ERRORS ====================================
ImportError: cannot import name 'is_reverse_image_request' from 'private_search.ai.actions'
```

That confirmed the new Task 2 surface was missing before implementation.

Green:

- Added `is_reverse_image_request(text: str) -> bool`.
- Allowed `reverse_image_search` to validate with `image_path=None` while keeping `describe_image` strict.
- Removed `ChatOrchestrator.active_image_path`, `set_active_image()`, `clear_active_image()`, and the active-image system-prompt augmentation.
- Added deterministic reverse-search forcing in `ChatOrchestrator.handle()` when the original user text contains both `reverse` and `search`.
- Added `reverse_image_resolver` support to `ToolRegistry`.
- Resolved missing reverse-search paths before confirmation, copied the chosen file path into the action with `dataclasses.replace()`, and cancelled cleanly when no path was provided.
- Kept unavailable-tool behavior intact when a reverse-search adapter is not configured and an image path is already present.
- Updated the action prompt so the app selects reverse-search images from the project image folder and the model does not invent paths.

Refactor:

- Kept the implementation minimal and limited to the requested files.

## Requirements checklist

- Added `is_reverse_image_request(text: str) -> bool`: yes
- True only when `reverse` and `search` occur as word tokens: yes
- Removed `ChatOrchestrator.active_image_path`: yes
- Removed `set_active_image()`: yes
- Removed `clear_active_image()`: yes
- Removed `Path` import from `chat.py`: yes
- Removed active-image system-prompt augmentation: yes
- Added `reverse_image_resolver: Callable[[], str | None] | None = None` to `ToolRegistry.__init__`: yes
- Resolve missing reverse-search image path before confirmation: yes
- Resolver `None` returns cancelled `ToolResult` without confirmation or adapter execution: yes
- Returned resolver path must be a regular file: yes
- Resolved path copied into the action with `dataclasses.replace()` before confirmation and execution: yes
- `reverse_image_search` allows `image_path: null`: yes
- `describe_image` still requires an image path: yes
- Action prompt updated to use the project image folder and forbid invented paths: yes
- `ChatOrchestrator.handle()` deterministically forces reverse-image action from user keywords and clears unrelated scalar fields: yes

## Tests added or updated

- `tests/test_reverse_search_selection.py`
  - phrase detection positive case
  - phrase detection negative case
- `tests/test_agent_actions.py`
  - prompt coverage for project image folder / invented-path guidance
  - reverse-image parsing with `image_path=None`
  - token-based reverse-search detection
  - describe-image validation remains strict
- `tests/test_chat.py`
  - deterministic reverse-search forcing clears unrelated fields
- `tests/test_tool_registry.py`
  - resolver-before-confirmation
  - exact resolved path passed to confirmation and adapter
  - cancellation when resolver returns `None`
  - unavailable behavior preserved when reverse-search adapter is absent

## Verification

Focused tests:

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_reverse_search_selection.py tests/test_agent_actions.py tests/test_chat.py tests/test_tool_registry.py
```

Result:

```text
35 passed in 0.22s
```

Ruff:

```powershell
.venv\Scripts\python.exe -m ruff check src tests main.py
```

Result:

```text
All checks passed!
```

## Self-review

What I checked:

- Reviewed the Task 2 source and test changes directly after verification.
- Searched for stale `active_image_path`, `set_active_image`, and `clear_active_image` references across `src` and `tests`.

Finding:

- `src/private_search/app/chat_ui.py` and `tests/test_chat_ui.py` still reference the removed `ChatOrchestrator` active-image APIs.
- I did not modify those files because the brief explicitly restricts Task 2 changes to the AI action/chat/tool files plus the listed tests, and also says not to modify Task 1 files.

Assessment:

- The required Task 2 files are implemented and the specified verification commands pass.
- There is an integration concern outside the allowed Task 2 edit scope: Task 1 UI code in the current dirty workspace still assumes the removed active-image methods exist.

## Commit scope

Intended commit contents:

- `src/private_search/ai/actions.py`
- `src/private_search/ai/chat.py`
- `src/private_search/ai/tools.py`
- `tests/test_reverse_search_selection.py`
- `tests/test_agent_actions.py`
- `tests/test_chat.py`
- `tests/test_tool_registry.py`
- this report file

No unrelated dirty files included.
