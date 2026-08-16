# Blackbird and InsightFace Theia Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Tookie with an isolated Blackbird OSINT worker and add an isolated InsightFace face-index worker that assists SmartImage reverse searches.

**Architecture:** Theia calls two JSON workers through deep adapters. Blackbird handles username/email OSINT; InsightFace owns local face analysis and SQLite index maintenance; SmartImage remains the external reverse-image adapter. Theia owns confirmation, normalization, confidence filtering, rendering, and lifecycle.

**Tech Stack:** Python 3.11+, subprocess JSON protocol, Blackbird’s isolated Python environment, InsightFace 1.0.1, ONNX Runtime GPU, NumPy, OpenCV, SQLite, SmartImage Rdx, pytest, Ruff.

## Global Constraints

- Blackbird replaces Tookie at runtime; Tookie is not invoked by Theia after integration.
- Heavy Blackbird and InsightFace dependencies stay out of Theia’s main Python environment.
- No Blackbird external AI API is used.
- `shell=False` is required for every worker process.
- External OSINT scans and image uploads remain confirmation-gated.
- Face embeddings remain local and temporary face crops are deleted after search unless explicitly saved.
- Image and face-similarity results below 75% are discarded before rendering and download selection.
- Blackbird `FOUND` output is displayed as `Verified site match`, not as a face-style probability.
- InsightFace GPU status must be verified from the active ONNX Runtime provider; no silent CPU claim is allowed.
- The persistent index is `var/face-index.sqlite`; face crops use `var/face-crops/`.
- Theia learning and preference memory are deferred until the deterministic pipeline is stable.
- The existing SmartImage subprocess and `.NET` fallback remain the external web-search implementation.

---

## File Map

### Shared worker and scoring modules

- Create: `src/private_search/osint/worker.py` — validated one-shot JSON worker launcher with timeout, bounded diagnostics, and `shell=False`.
- Create: `src/private_search/osint/confidence.py` — source-aware numeric score parsing, normalization, bands, and the 75% filter.
- Modify: `src/private_search/config.py` — Blackbird/InsightFace paths, environments, index, crop, and timeout settings.
- Test: `tests/test_worker.py`, `tests/test_confidence.py`.

### Blackbird

- Create: `src/private_search/osint/blackbird.py` — deep Theia adapter for username/email requests and normalized records.
- Create: `Update/blackbird/theia_worker.py` — JSON stdin/stdout worker that bootstraps Blackbird core modules without invoking `blackbird.py` argument parsing.
- Modify: `Update/blackbird/src/modules/utils/http_client.py` — restore certificate verification and preserve configured proxy behavior.
- Modify: `src/private_search/osint/__init__.py` — export Blackbird adapter and errors.
- Test: `tests/test_blackbird.py`, `Update/blackbird/tests/test_theia_worker.py`.

### Actions, registry, and UI

- Modify: `src/private_search/ai/actions.py` — add `email_osint`, `email`, and exact prompt/schema behavior.
- Modify: `src/private_search/ai/tools.py` — add the Blackbird username/email adapters and keep one confirmation per external scan.
- Modify: `src/private_search/app/chat_ui.py` — replace Tookie wiring, render username/email results, and render scored face/web groups.
- Modify: `src/private_search/ai/chat.py` — preserve deterministic action normalization and handle the new email action.
- Test: `tests/test_agent_actions.py`, `tests/test_tool_registry.py`, `tests/test_chat.py`, `tests/test_chat_ui.py`.

### InsightFace index and worker

- Create: `src/private_search/osint/face_store.py` — deep SQLite face-index module with schema migration, refresh bookkeeping, batched writes, and vector search.
- Create: `src/private_search/osint/insightface.py` — Theia adapter for local face analysis and face-assisted SmartImage orchestration.
- Create: `src/private_search/osint/insightface_worker.py` — isolated worker that loads InsightFace once per request, validates the active provider, refreshes the index, and returns local matches plus crop paths.
- Modify: `src/private_search/osint/smartimage.py` — expose an internal search method usable by the face-assisted adapter without a second confirmation prompt.
- Test: `tests/test_face_store.py`, `tests/test_insightface.py`, `tests/test_face_assisted_search.py`.

### Setup and documentation

- Create: `scripts/setup_blackbird.ps1` — create/update Blackbird’s isolated environment and install its requirements.
- Create: `scripts/setup_insightface.ps1` — create/update InsightFace’s isolated environment, install GPU runtime, and verify providers.
- Modify: `.env.example` — document worker interpreters, roots, timeouts, model, index, and CUDA settings.
- Modify: `README.md` — add setup, GPU verification, local index behavior, licensing, and troubleshooting.
- Modify: `docs/architecture.md` — document worker seams and result flow.
- Test: `tests/test_setup_config.py`, plus manual smoke commands documented in README.

---

### Task 1: Add shared worker launcher and confidence module

**Files:**
- Create: `src/private_search/osint/worker.py`
- Create: `src/private_search/osint/confidence.py`
- Modify: `src/private_search/config.py`
- Test: `tests/test_worker.py`
- Test: `tests/test_confidence.py`

**Interfaces:**
- `run_json_worker(command: Sequence[str], request: Mapping[str, object], *, cwd: Path, timeout_seconds: int, env: Mapping[str, str] | None = None) -> object`.
- `WorkerExecutionError` carries a safe user-facing message and truncated diagnostics.
- `normalize_score(value: object, *, source: str) -> float | None` returns a clamped presentation score from `0.0` to `100.0`.
- `confidence_band(score: float) -> str` returns `Accurate`, `More likely`, or `Possible` for scores at or above 75.
- `filter_confident(results: Iterable[Mapping[str, object]], *, field: str = "confidence", minimum: float = 75.0) -> list[dict[str, object]]` removes numeric results below the threshold and preserves stable ordering.

- [ ] **Step 1: Write failing worker and confidence tests.**

Test JSON parsing, malformed output, non-zero exit, timeout, shell disabling, bounded diagnostics, score parsing for `0.82`, `82`, empty values, clamping, bands, and stable filtering.

- [ ] **Step 2: Run focused tests and verify failure.**

Run: `python -m pytest tests/test_worker.py tests/test_confidence.py -q`

Expected: FAIL because the new modules and interfaces do not exist.

- [ ] **Step 3: Implement the deep modules.**

Use `subprocess.run(..., shell=False, capture_output=True, text=True, timeout=...)`; pass request JSON through stdin; parse exactly one JSON value; truncate diagnostics to 2,000 characters. Use `math.isfinite`, clamp scores, and avoid copying result lists more than once.

- [ ] **Step 4: Run focused tests.**

Run: `python -m pytest tests/test_worker.py tests/test_confidence.py -q`

Expected: PASS.

- [ ] **Step 5: Commit.**

```powershell
git add src/private_search/osint/worker.py src/private_search/osint/confidence.py src/private_search/config.py tests/test_worker.py tests/test_confidence.py
git commit -m "feat: add worker protocol and confidence filtering"
```

### Task 2: Build the Blackbird JSON worker and adapter

**Files:**
- Create: `Update/blackbird/theia_worker.py`
- Create: `src/private_search/osint/blackbird.py`
- Modify: `Update/blackbird/src/modules/utils/http_client.py`
- Modify: `src/private_search/osint/__init__.py`
- Test: `tests/test_blackbird.py`
- Test: `Update/blackbird/tests/test_theia_worker.py`

**Interfaces:**
- `BlackbirdSettings.from_environment() -> BlackbirdSettings` resolves the Blackbird root, Python executable, timeout, thread limit, and update policy.
- `BlackbirdAdapter.__call__(action: AgentAction) -> list[dict[str, object]]` supports `username_osint` and `email_osint`.
- Worker request operations are exactly `username` and `email`; values are validated before network work.

- [ ] **Step 1: Write failing adapter and worker tests.**

Cover safe subprocess command construction, isolated working directory, JSON parsing, username/email validation, update-list failure, normalized `FOUND` records, and disabled external AI.

- [ ] **Step 2: Run focused tests and verify failure.**

Run: `python -m pytest tests/test_blackbird.py Update/blackbird/tests/test_theia_worker.py -q`

Expected: FAIL because the worker and adapter are absent.

- [ ] **Step 3: Implement the worker.**

Bootstrap Blackbird’s existing core modules from `src/modules`, configure `Console(file=sys.stderr)`, absolute data paths, bounded concurrency, timeouts, and `checkUpdates`. Emit one JSON object to stdout and diagnostics only to stderr. Do not call `blackbird.py` or its `argparse` path. Keep JSON records explicit rather than serializing arbitrary config state.

- [ ] **Step 4: Harden transport and implement the adapter.**

Change Blackbird’s HTTP client to use `verify=True` by default. The adapter launches the worker through `run_json_worker`, passes an isolated environment, and returns normalized records with `source`, `kind`, `site`, `url`, `status`, `category`, and `metadata`.

- [ ] **Step 5: Run focused tests.**

Run: `python -m pytest tests/test_blackbird.py Update/blackbird/tests/test_theia_worker.py -q`

Expected: PASS.

- [ ] **Step 6: Commit.**

```powershell
git add Update/blackbird/theia_worker.py Update/blackbird/src/modules/utils/http_client.py Update/blackbird/tests/test_theia_worker.py src/private_search/osint/blackbird.py src/private_search/osint/__init__.py tests/test_blackbird.py
git commit -m "feat: add isolated Blackbird OSINT worker"
```

### Task 3: Replace Tookie in actions, registry, chat, and rendering

**Files:**
- Modify: `src/private_search/ai/actions.py`
- Modify: `src/private_search/ai/tools.py`
- Modify: `src/private_search/ai/chat.py`
- Modify: `src/private_search/app/chat_ui.py`
- Modify: `src/private_search/osint/__init__.py`
- Test: `tests/test_agent_actions.py`
- Test: `tests/test_tool_registry.py`
- Test: `tests/test_chat.py`
- Test: `tests/test_chat_ui.py`

**Interfaces:**
- `AgentAction.email` is optional text and is required only for `email_osint`.
- `ToolRegistry(..., username_osint_tool=BlackbirdAdapter(), email_osint_tool=BlackbirdAdapter())` confirms before dispatch.
- The username/email renderer consumes normalized Blackbird records and never assumes Tookie’s `found` field.

- [ ] **Step 1: Add failing action and registry tests.**

Cover `email_osint` JSON validation, missing email rejection, confirmation details, adapter dispatch, Tookie absence from chat wiring, and normalized result rendering.

- [ ] **Step 2: Run focused tests and verify failure.**

Run: `python -m pytest tests/test_agent_actions.py tests/test_tool_registry.py tests/test_chat.py tests/test_chat_ui.py -q`

Expected: FAIL for the new action and replacement wiring.

- [ ] **Step 3: Implement action and registry changes.**

Extend the strict schema and system prompt with `email_osint`; keep all external scans confirmation-gated. Add a separate adapter slot and `ToolResult` message path. Do not leave a fallback to Tookie.

- [ ] **Step 4: Update chat UI and deterministic normalization.**

Replace `TookieAdapter` construction with `BlackbirdAdapter`. Add a compact email result table and retain username source/status/URL details. Keep model-generated paths and commands prohibited.

- [ ] **Step 5: Run focused tests.**

Run: `python -m pytest tests/test_agent_actions.py tests/test_tool_registry.py tests/test_chat.py tests/test_chat_ui.py -q`

Expected: PASS.

- [ ] **Step 6: Commit.**

```powershell
git add src/private_search/ai/actions.py src/private_search/ai/tools.py src/private_search/ai/chat.py src/private_search/app/chat_ui.py src/private_search/osint/__init__.py tests/test_agent_actions.py tests/test_tool_registry.py tests/test_chat.py tests/test_chat_ui.py
git commit -m "feat: replace Tookie with Blackbird actions"
```

### Task 4: Implement the persistent SQLite face index

**Files:**
- Create: `src/private_search/osint/face_store.py`
- Modify: `src/private_search/config.py`
- Test: `tests/test_face_store.py`

**Interfaces:**
- `FaceIndex(path: Path)` opens SQLite with WAL mode, foreign keys, and a busy timeout.
- `FaceIndex.refresh_images(images: Sequence[ImageRecord], *, model_version: str) -> RefreshReport` batches inserts/updates and removes records for deleted images.
- `FaceIndex.upsert_faces(image: ImageRecord, faces: Sequence[FaceRecord]) -> None` stores normalized embeddings as BLOBs and replaces prior face rows in one transaction.
- `FaceIndex.search(embedding: Sequence[float], *, limit: int) -> list[FaceMatch]` loads only required columns, computes vectorized cosine similarity, and returns deterministic descending matches.

- [ ] **Step 1: Write failing schema and lifecycle tests.**

Cover schema creation, WAL/foreign-key pragmas, new/changed/unchanged/deleted images, model-version rebuild, batched upsert, cosine ranking, empty index, and deterministic tie ordering.

- [ ] **Step 2: Run focused tests and verify failure.**

Run: `python -m pytest tests/test_face_store.py -q`

Expected: FAIL because `face_store.py` does not exist.

- [ ] **Step 3: Implement the SQLite module.**

Use explicit columns and parameterized SQL. Add indexes on `images(path)`, `images(content_hash)`, and `faces(image_id)`. Use one transaction per refresh batch, `executemany` for face rows, `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`, and `PRAGMA busy_timeout=5000`. Store little-endian float32 embeddings without JSON expansion.

- [ ] **Step 4: Run focused tests and inspect query plans.**

Run: `python -m pytest tests/test_face_store.py -q`

Then verify the image lookup and face lookup use their indexes with SQLite `EXPLAIN QUERY PLAN` in a test helper or diagnostic command.

- [ ] **Step 5: Commit.**

```powershell
git add src/private_search/osint/face_store.py src/private_search/config.py tests/test_face_store.py
git commit -m "feat: add persistent SQLite face index"
```

### Task 5: Add InsightFace worker and face-assisted SmartImage adapter

**Files:**
- Create: `src/private_search/osint/insightface_worker.py`
- Create: `src/private_search/osint/insightface.py`
- Modify: `src/private_search/osint/smartimage.py`
- Modify: `src/private_search/osint/__init__.py`
- Test: `tests/test_insightface.py`
- Test: `tests/test_face_assisted_search.py`

**Interfaces:**
- `InsightFaceSettings.from_environment() -> InsightFaceSettings` resolves the worker interpreter, model name, image directory, index path, crop directory, timeout, and provider policy.
- `InsightFaceAdapter.analyze_and_search(image_path: Path, *, smartimage: SmartImageAdapter) -> list[dict[str, object]]` returns separate `local_face` and `web_reverse` records.
- The worker request operations are `analyze`, `refresh`, and `reverse`; each response includes `provider`, `model_version`, `faces`, `local_matches`, and `crops`.

- [ ] **Step 1: Write failing worker, provider, crop, and orchestration tests.**

Use fake InsightFace modules and fake SmartImage adapters. Cover active CUDA reporting, explicit CPU degradation, multiple faces, crop cleanup, index reuse, full-image plus crop invocation, result provenance, deduplication, and filtering below 75%.

- [ ] **Step 2: Run focused tests and verify failure.**

Run: `python -m pytest tests/test_insightface.py tests/test_face_assisted_search.py -q`

Expected: FAIL because the worker, adapter, and SmartImage internal method are absent.

- [ ] **Step 3: Implement the worker.**

Load `FaceAnalysis` once per request and prefer `CUDAExecutionProvider` followed by `CPUExecutionProvider` only when the policy permits fallback. Verify `onnxruntime.get_available_providers()` and return the actual selected provider. Analyze supported images in the configured `image` folder, create aligned temporary crops, update the SQLite index, and return compact metadata plus crop paths.

- [ ] **Step 4: Add SmartImage internal search seam and orchestration.**

Refactor the existing adapter so its public confirmation-gated call remains unchanged while a private/internal `search_image(path)` method can be called by the confirmed face-assisted adapter. Search the original image and each crop, tag provenance, normalize numeric scores, deduplicate by URL, and call `filter_confident(..., minimum=75.0)` before returning data.

- [ ] **Step 5: Run focused tests.**

Run: `python -m pytest tests/test_insightface.py tests/test_face_assisted_search.py tests/test_smartimage.py -q`

Expected: PASS.

- [ ] **Step 6: Commit.**

```powershell
git add src/private_search/osint/insightface_worker.py src/private_search/osint/insightface.py src/private_search/osint/smartimage.py src/private_search/osint/__init__.py tests/test_insightface.py tests/test_face_assisted_search.py tests/test_smartimage.py
git commit -m "feat: add InsightFace-assisted SmartImage search"
```

### Task 6: Wire the built-in face capability and remove Tookie runtime use

**Files:**
- Modify: `src/private_search/app/chat_ui.py`
- Modify: `src/private_search/ai/tools.py`
- Modify: `src/private_search/osint/__init__.py`
- Delete: `src/private_search/osint/tookie.py`
- Delete: `tests/test_tookie.py`
- Test: `tests/test_main.py`
- Test: `tests/test_reverse_search_selection.py`

**Interfaces:**
- `ToolRegistry` receives one `reverse_image_tool=FaceAssistedReverseImageAdapter(...)` and no Tookie adapter.
- Reverse-image selection continues to resolve images from the project `image` folder.
- The existing action remains `reverse_image_search`; InsightFace processing is hidden behind the adapter interface.

- [ ] **Step 1: Add failing wiring tests.**

Assert Theia constructs Blackbird for username/email, InsightFace-assisted search for reverse images, and no Tookie import or runtime path remains.

- [ ] **Step 2: Run focused tests and verify failure.**

Run: `python -m pytest tests/test_main.py tests/test_reverse_search_selection.py -q`

Expected: FAIL until chat wiring is changed.

- [ ] **Step 3: Replace runtime wiring.**

Construct the configured adapters in `interactive_chat`, retain the existing project-image resolver, and keep confirmation at the registry seam. Remove the Tookie import, settings, and tests only after the replacement tests cover the same behavior.

- [ ] **Step 4: Run focused tests.**

Run: `python -m pytest tests/test_main.py tests/test_reverse_search_selection.py tests/test_tool_registry.py -q`

Expected: PASS.

- [ ] **Step 5: Commit.**

```powershell
git add src/private_search/app/chat_ui.py src/private_search/ai/tools.py src/private_search/osint/__init__.py tests/test_main.py tests/test_reverse_search_selection.py
git rm src/private_search/osint/tookie.py tests/test_tookie.py
git commit -m "feat: make Blackbird and InsightFace native Theia capabilities"
```

### Task 7: Add setup scripts, configuration, and documentation

**Files:**
- Create: `scripts/setup_blackbird.ps1`
- Create: `scripts/setup_insightface.ps1`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Test: `tests/test_setup_config.py`

**Interfaces:**
- Setup scripts are repeatable and fail fast on missing Python, pip, or NVIDIA provider prerequisites.
- Environment variables use `PRIVATE_SEARCH_BLACKBIRD_*` and `PRIVATE_SEARCH_INSIGHTFACE_*` prefixes.

- [ ] **Step 1: Write failing configuration tests.**

Cover default paths, explicit interpreter overrides, timeout validation, model/index paths, and no accidental use of the main environment for worker launches.

- [ ] **Step 2: Implement repeatable setup scripts and configuration.**

Create the two virtual environments, install their requirements, install the uploaded InsightFace package, install `onnxruntime-gpu` instead of CPU-only `onnxruntime`, and run a provider check. Do not download model weights without an explicit setup command or documented confirmation.

- [ ] **Step 3: Write user-facing documentation.**

Document installation, GPU verification, model-license limits, local index location, image-folder refresh behavior, confidence filtering, worker troubleshooting, Blackbird site-list updates, and the confirmation/privacy behavior. Keep setup instructions task-oriented and reference details separate from explanation.

- [ ] **Step 4: Run focused tests and documentation checks.**

Run: `python -m pytest tests/test_setup_config.py -q`

Expected: PASS.

- [ ] **Step 5: Commit.**

```powershell
git add scripts/setup_blackbird.ps1 scripts/setup_insightface.ps1 .env.example README.md docs/architecture.md tests/test_setup_config.py
git commit -m "docs: add Blackbird and InsightFace setup"
```

### Task 8: Full verification and performance checks

**Files:**
- Modify: `docs/superpowers/sdd/blackbird-insightface-theia-integration/progress.md`
- Test: all project tests

- [ ] **Step 1: Run lint and focused regression tests.**

Run:

```powershell
ruff check src tests
python -m pytest tests/test_worker.py tests/test_confidence.py tests/test_blackbird.py tests/test_face_store.py tests/test_insightface.py tests/test_face_assisted_search.py -q
```

- [ ] **Step 2: Run the complete test suite.**

Run: `python -m pytest -q`

Expected: all tests pass with no Tookie runtime imports.

- [ ] **Step 3: Run setup and provider smoke checks.**

Run the two setup scripts in a configured environment, then verify that the InsightFace worker reports `CUDAExecutionProvider` on the RTX 5080 or clearly reports the explicit CPU degraded mode.

- [ ] **Step 4: Measure the index hot path.**

Use `python -m cProfile` or `timeit` around refresh of unchanged images and local vector search. Confirm unchanged images do not reload embeddings and SQLite queries use the intended indexes. Keep model inference and network time separate from index time.

- [ ] **Step 5: Run the manual acceptance flow.**

Start Theia, run a username search, an email search, and reverse search on an image with one and multiple faces. Confirm one external confirmation, local face results, SmartImage provenance, removal of scores below 75%, crop cleanup, and graceful worker errors.

- [ ] **Step 6: Commit verification artifacts only if they are project documentation.**

Do not commit generated databases, model weights, logs, temporary crops, or environment directories. Commit only the progress ledger and documentation updates.

## Review checklist

- [ ] Every worker has a small interface and a deep implementation behind it.
- [ ] No worker imports a CLI parser or emits non-JSON stdout.
- [ ] No external AI API is used.
- [ ] No face embedding leaves the local machine except through an explicit SmartImage upload of a selected crop.
- [ ] SQLite writes are batched and indexed queries are verified.
- [ ] Unchanged images avoid reprocessing.
- [ ] Confidence scores below 75% never reach the renderer.
- [ ] Existing SmartImage behavior and Windows dotnet fallback remain covered.
- [ ] README and architecture docs explain setup, privacy, and license limits.
