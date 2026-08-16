# Task 7 Report

Date: 2026-08-16

## Status

Complete.

## Changed files

- `.env.example`
- `README.md`
- `docs/architecture.md`
- `scripts/setup_blackbird.ps1`
- `scripts/setup_insightface.ps1`
- `src/private_search/config.py`
- `src/private_search/osint/blackbird.py`
- `src/private_search/osint/insightface.py`
- `tests/test_setup_config.py`

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
- Integrated user-facing setup, privacy, licensing, troubleshooting, and worker
  boundary documentation into the existing README and architecture docs.
- Did not modify the SDD ledger.

## Verification

Required pytest:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_setup_config.py -q
```

Output:

```text
9 passed in 0.02s
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

Additional focused regression verification:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_setup_config.py tests/test_blackbird.py tests/test_insightface.py -q
.\.venv\Scripts\python.exe -m ruff check src/private_search/config.py src/private_search/osint/blackbird.py src/private_search/osint/insightface.py tests/test_setup_config.py
```

Output:

```text
25 passed in 0.68s
All checks passed!
```
