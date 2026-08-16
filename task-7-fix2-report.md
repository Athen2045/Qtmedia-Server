# Task 7 Fix Round 2 Report

Date: 2026-08-16

Base commit: `d1079a0`

## Scope

Applied the scoped review fixes from `.superpowers/sdd/blackbird-insightface-theia-integration/task-7-fix2-brief.md` without modifying the SDD ledger.

## Changes

- Added non-mutating regression coverage in `tests/test_setup_config.py` that inspects both setup scripts and verifies each enforces a Python 3.11+ guard before venv creation and pip installation.
- Corrected `task-7-report.md` and `task-7-fix-report.md` so they name the committed `d1079a0` baseline and record the current passing verification without pending language.
- Left setup/runtime implementation unchanged because the new regression coverage confirmed the existing scripts already enforce the intended guard ordering.

## Verification

Required pytest:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_setup_config.py -q
```

Output:

```text
14 passed in 0.03s
```

Required Ruff:

```powershell
.\.venv\Scripts\python.exe -m ruff check src/private_search/config.py tests/test_setup_config.py
```

Output:

```text
All checks passed!
```

PowerShell parser checks:

```powershell
$parseErrors = @(); [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path 'scripts/setup_blackbird.ps1'), [ref]$null, [ref]$parseErrors) | Out-Null; [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path 'scripts/setup_insightface.ps1'), [ref]$null, [ref]$parseErrors) | Out-Null; if ($parseErrors.Count -gt 0) { $parseErrors | ForEach-Object { $_.Message }; exit 1 }
```

Result:

```text
No parse errors.
```

## Commit

Message: `test: cover isolated setup version guards`
