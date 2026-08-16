# Task 7 Fix Report

Date: 2026-08-16

## Scope

Applied the scoped review fixes from `.superpowers/sdd/blackbird-insightface-theia-integration/task-7-fix-brief.md` without touching the SDD ledger.

## Planned file scope

- `scripts/setup_blackbird.ps1`
- `scripts/setup_insightface.ps1`
- `src/private_search/config.py`
- `tests/test_setup_config.py`
- `task-7-report.md`

## Implemented fixes

- Added a small `Assert-Python311OrNewer` helper to both setup scripts so the chosen interpreter is rejected before any venv creation or package installation if it is older than Python 3.11.
- Hardened `src/private_search/config.py` so malformed integer environment variables raise `ConfigurationError` with the exact variable name, while keeping the existing minimum-value validation.
- Expanded `tests/test_setup_config.py` with regression coverage for malformed Blackbird timeout/thread values and malformed InsightFace timeout values.
- Corrected `task-7-report.md` so it reflects the follow-up fix and fresh verification.

## Verification to record after commit

Required pytest:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_setup_config.py -q
```

Output:

```text
12 passed in 0.03s
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

Message: `fix: harden isolated setup validation`

Hash: Pending until committed.
