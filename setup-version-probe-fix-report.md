# Setup Version-Probe Fix Report

Date: 2026-08-16

## Summary

Implemented the Windows-safe setup version-probe fix for both setup scripts by replacing the fragile quoted version-print probe with a quote-safe exit-only Python expression:

`sys.exit(0 if sys.version_info >= (3, 11) else 1)`

This keeps the existing Python 3.11+ gate and launcher fallback flow intact while avoiding the broken f-string argument boundary behavior in PowerShell.

## TDD Record

### Red

Added `test_setup_scripts_use_quote_safe_python_version_probe` to `tests/test_setup_config.py` first, then ran:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_setup_config.py
```

Observed expected failure:

- `test_setup_scripts_use_quote_safe_python_version_probe[setup_blackbird.ps1]`
- `test_setup_scripts_use_quote_safe_python_version_probe[setup_insightface.ps1]`

Both failures showed the scripts did not yet contain:

`sys.exit(0 if sys.version_info >= (3, 11) else 1)`

### Green

Made the minimal production change in:

- `scripts/setup_blackbird.ps1`
- `scripts/setup_insightface.ps1`

Updated the existing setup guard assertion in `tests/test_setup_config.py` to match the new probe.

## Verification

Ran:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_setup_config.py
.\.venv\Scripts\python.exe -m ruff check tests\test_setup_config.py
$parseErrors = @(); [System.Management.Automation.Language.Parser]::ParseFile('C:\Users\Allan MJ\Documents\My Work\Um\scripts\setup_blackbird.ps1', [ref]$null, [ref]$parseErrors) | Out-Null; [System.Management.Automation.Language.Parser]::ParseFile('C:\Users\Allan MJ\Documents\My Work\Um\scripts\setup_insightface.ps1', [ref]$null, [ref]$parseErrors) | Out-Null; if ($parseErrors.Count -gt 0) { $parseErrors | ForEach-Object { $_.Message }; exit 1 }
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
```

Results:

- `pytest`: 18 passed
- `ruff`: all checks passed
- PowerShell parser: no parse errors
- Version-probe smoke: exited successfully with the working `python.exe` (Python 3.14.6)

## Scope Notes

- Did not modify the SDD ledger.
- Did not install dependencies.
- Kept the change limited to the setup scripts, the setup regression test, and this report.
