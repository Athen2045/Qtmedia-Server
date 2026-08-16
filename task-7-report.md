# Task 7 Report

Date: 2026-08-16

## Status

Complete with follow-up fixes from the Task 7 review.

## Changed files

- `.env.example`
- `README.md`
- `docs/architecture.md`
- `scripts/setup_blackbird.ps1`
- `scripts/setup_insightface.ps1`
- `src/private_search/config.py`
- `tests/test_setup_config.py`
- `task-7-report.md`
- `task-7-fix-report.md`

## Notes

- Added typed Blackbird and InsightFace runtime settings in `config.py` so the
  worker roots, interpreters, timeouts, provider policy, index path, crop path,
  and keep-crops behavior are validated in one place.
- Changed the default Blackbird worker interpreter to its isolated
  `Update/blackbird/.venv` path so the main project `.venv` is not used
  accidentally.
- Added repeatable PowerShell setup scripts for the isolated Blackbird and
  InsightFace environments. The InsightFace script installs the uploaded package
  without downloading model weights and pins `onnxruntime-gpu==1.27.0`.
- Follow-up review fix: both setup scripts now fail before environment creation
  or package installation when the selected interpreter is older than Python
  3.11.
- Follow-up review fix: malformed numeric worker settings now raise
  `ConfigurationError` with the environment variable name while keeping the
  existing range validation.
- Did not modify the SDD ledger.

## Verification

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
[System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path 'scripts\setup_blackbird.ps1'), [ref]$null, [ref]$errors)
[System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path 'scripts\setup_insightface.ps1'), [ref]$null, [ref]$errors)
```

Result:

```text
No parse errors.
```

Follow-up fix commit:

```powershell
fix: harden isolated setup validation
```

Commit hash:

```text
Pending until committed.
```
