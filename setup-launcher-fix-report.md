# Setup Launcher Fix Report

Date: 2026-08-16

## Scope

Implemented the launcher fallback fix from `.superpowers/sdd/blackbird-insightface-theia-integration/setup-launcher-fix-brief.md` without modifying the SDD ledger or installing dependencies.

## Root Cause

Both PowerShell setup scripts returned the first discovered launcher candidate immediately after running `--version`, even when the native `py` probe exited non-zero. On this machine that caused `py -3.11` or `py -3` to be selected even though only `python` was usable.

## TDD Evidence

Red:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_setup_config.py -k native_python_launcher_probes
```

Observed failure before the fix:

```text
FAILED tests/test_setup_config.py::test_setup_scripts_skip_failed_native_python_launcher_probes[setup_blackbird.ps1]
FAILED tests/test_setup_config.py::test_setup_scripts_skip_failed_native_python_launcher_probes[setup_insightface.ps1]
ValueError: substring not found
```

Green:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_setup_config.py -k native_python_launcher_probes
```

Observed after the fix:

```text
2 passed, 14 deselected
```

## Changes

- Added a regression test in `tests/test_setup_config.py` that requires each setup script to check `$LASTEXITCODE`, `continue` on native probe failure, and only then `return $candidate`.
- Updated `scripts/setup_blackbird.ps1` so `Resolve-PythonLauncher` continues to the next candidate when the `--version` probe exits non-zero.
- Updated `scripts/setup_insightface.ps1` with the same minimal fallback behavior.

## Verification

Pytest regression:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_setup_config.py -k native_python_launcher_probes
```

Result:

```text
2 passed, 14 deselected
```

Setup-config suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_setup_config.py
```

Result:

```text
16 passed
```

Ruff:

```powershell
.\.venv\Scripts\python.exe -m ruff check tests/test_setup_config.py
```

Result:

```text
All checks passed!
```

PowerShell parser checks:

```powershell
$errors = $null; $tokens = $null; [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path 'scripts/setup_blackbird.ps1'), [ref]$tokens, [ref]$errors) | Out-Null; if ($errors.Count -ne 0) { $errors | ForEach-Object { $_.Message }; exit 1 }
$errors = $null; $tokens = $null; [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path 'scripts/setup_insightface.ps1'), [ref]$tokens, [ref]$errors) | Out-Null; if ($errors.Count -ne 0) { $errors | ForEach-Object { $_.Message }; exit 1 }
```

Result:

```text
No parse errors.
```

## Commit

Requested commit message:

`fix: fall back to available Python launcher`
