# Task 4 Report

Date: 2026-08-16
Base commit: `b020bc3bbb52e77e1b9c8aef8ec738e688dd31a1`
Commit: `feat: add persistent SQLite face index`

## Changed files

- `src/private_search/config.py`
- `src/private_search/osint/face_store.py`
- `tests/test_face_store.py`

## Notes

- Implemented the persistent SQLite-backed `FaceIndex` with immutable typed records, schema creation, WAL/foreign-key/busy-timeout pragmas, explicit indexes, batched refresh/upsert transactions, normalized float32 embedding blobs, and deterministic cosine match ordering.
- Kept the config surface minimal by adding `FACE_INDEX_PATH`, `FACE_CROP_ROOT`, and runtime directory creation for the face-crop root.
- Strengthened the focused face-store tests to cover deterministic refresh ordering, content-hash index visibility, invalid path handling, embedding normalization, lifecycle refresh behavior, query-plan assertions, and safe close/context-manager behavior.
- Preserved unrelated working tree changes and did not modify the SDD ledger.

## Verification

Pytest command:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_face_store.py -q
```

Pytest output:

```text
............                                                             [100%]
12 passed in 0.31s
```

Ruff command:

```powershell
.venv\Scripts\python.exe -m ruff check src/private_search/osint/face_store.py src/private_search/config.py tests/test_face_store.py
```

Ruff output:

```text
All checks passed!
```

## Concerns

- Search currently computes cosine similarity in Python over the loaded face rows, which is acceptable for the current local-store scope but may need a more vectorized path if the face index grows substantially.
