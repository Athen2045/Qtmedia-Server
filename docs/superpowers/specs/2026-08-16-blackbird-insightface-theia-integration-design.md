# Blackbird and InsightFace Theia Integration

Date: 2026-08-16
Status: Approved design

## Summary

Theia will gain two new built-in capabilities behind isolated worker processes:

1. Blackbird replaces Tookie as the username OSINT backend and also provides email OSINT.
2. InsightFace performs local face detection, alignment, embedding, persistent indexing, and face-assisted SmartImage reverse search.

Theia remains the owner of confirmation, worker lifecycle, JSON validation, result normalization, confidence filtering, terminal rendering, and cleanup. The local model may orchestrate these capabilities only after the deterministic pipeline is stable. Preference learning is explicitly deferred to the final phase.

## Goals

- Replace the Tookie runtime integration with Blackbird.
- Provide username and email OSINT through a structured Blackbird worker.
- Add local face detection, cropping, matching, and persistent indexing through InsightFace.
- Use detected face crops as optional SmartImage reverse-search inputs.
- Keep heavy dependencies out of Theia's main Python environment.
- Keep all external scans and image uploads confirmation-gated.
- Filter image and face-similarity results below 75% before rendering.
- Verify and report the actual InsightFace execution provider, including CUDA availability.
- Preserve a compact Rich terminal experience with normalized results.

## Non-goals

- Translating SmartImage into Python.
- Importing Blackbird's CLI entry point into Theia.
- Running Blackbird's external AI API.
- Claiming that a face embedding proves a person's real-world identity.
- Silently retraining or fine-tuning the Qwen model.
- Building a cloud face-recognition service.
- Persisting temporary SmartImage upload crops by default.

## Current project context

The current Theia application has a confirmation-gated `username_osint` action wired to Tookie and a subprocess SmartImage adapter. The uploaded Blackbird tree is a CLI-oriented Python application that uses the WhatsMyName site list, assumes its own working directory, writes JSON to files, and includes an external AI API path. The uploaded InsightFace tree contains the Python package at `Update/insightface/python-package` and a separate Linux/Docker-oriented server.

The existing Windows application should use the InsightFace Python package in an isolated worker, not the uploaded server. The server remains a possible future deployment for Linux/WSL2 environments.

## Architecture

```text
Theia terminal UI and model orchestrator
  ├─ Blackbird worker       → normalized username/email records
  ├─ InsightFace worker     → faces, embeddings, local matches, crop paths
  └─ SmartImage worker      → external reverse-image records
```

Theia owns:

- confirmation prompts;
- validated action dispatch;
- fixed worker paths and `shell=False` process creation;
- timeouts and cancellation;
- strict JSON request/response validation;
- result normalization and deduplication;
- confidence scoring and filtering;
- Rich rendering;
- temporary-file cleanup;
- concise user-facing errors and detailed local diagnostics.

Workers own only their specialist operation and must not control Theia's shell, prompts, or model behavior.

## Capability 1: Blackbird OSINT

### Public Theia actions

- `username_osint`: search one username.
- `email_osint`: search one email address.
- Explicit permutation mode is out of scope for this implementation and is not enabled implicitly.

Tookie is removed from runtime wiring, settings, documentation, and tests after Blackbird reaches parity with the existing username action.

### Worker contract

The worker accepts a validated request such as:

```json
{"operation":"username","value":"alice","update_sites":true}
```

It returns normalized JSON records such as:

```json
{
  "source": "blackbird",
  "kind": "username",
  "site": "Example",
  "url": "https://example.com/alice",
  "status": "FOUND",
  "category": "social",
  "metadata": []
}
```

The worker runs from Blackbird's own root, uses a temporary output directory, and never relies on Theia's current working directory. It does not import the CLI entry point for orchestration.

### Blackbird hardening

Before integration:

- enable TLS certificate verification;
- disable the external Blackbird AI path;
- disable HTML dumps unless explicitly requested;
- validate usernames and emails before invoking the worker;
- bound concurrency and request timeouts;
- keep the WhatsMyName update cache local and refresh it according to an explicit cache policy;
- preserve source, category, metadata, and status in normalized output;
- deduplicate by canonical site and URL.

`FOUND` means Blackbird's configured site marker matched. It is displayed as `Verified site match`, not as a face-style probability that would imply confirmed ownership of an account.

## Capability 2: InsightFace local face index

### Runtime

InsightFace is installed from the uploaded `Update/insightface/python-package` into a dedicated environment:

```text
Update/insightface/.venv
```

The worker uses ONNX Runtime GPU where available and reports the active provider. It must not silently claim CUDA when it is running on CPU. CPU mode is an explicit degraded mode.

The uploaded InsightFace Server is not the primary target because its documented runtime is Linux x86_64 with Docker. The Windows application uses the Python package directly.

### Persistent storage

```text
var/face-index.sqlite
var/face-crops/
```

The index stores:

- canonical image path;
- file hash, size, and modification time;
- image dimensions;
- InsightFace model/version identifier;
- face count;
- face bounding boxes and landmarks;
- normalized embeddings;
- stable local face IDs;
- crop metadata and lifecycle state.

Index refresh rules:

- new image: analyze and add;
- changed image: remove old records and reprocess;
- unchanged image: reuse the existing records;
- deleted image: remove its records and crops;
- model-version change: rebuild affected records.

“Tracking” means consistent local similarity and clustering across the configured image folder. It does not assign a real-world identity without a user-created reference label.

### Face-assisted reverse search

1. Theia resolves the selected image from the project image folder.
2. The InsightFace worker refreshes the local index.
3. InsightFace detects faces and creates local embeddings.
4. Theia searches the local index for matching faces.
5. Temporary crops are created for detected faces.
6. Theia requests confirmation before submitting the original image or crops externally.
7. SmartImage searches the full image and face crops.
8. Results are normalized, deduplicated, scored, and filtered below 75%.
9. Temporary crops are deleted unless explicitly saved.

When multiple faces are detected, each crop is searched and results are labeled with the corresponding face number. Local face matches and SmartImage web results are displayed as separate groups.

## Confidence and result policy

Theia must not treat every provider's raw score as directly comparable. SmartImage similarity is provider-specific, InsightFace uses embedding similarity, and Blackbird returns site-verification states.

For image and face-similarity results, Theia normalizes scores into these presentation bands:

- `94–100%`: Accurate
- `80–93%`: More likely
- `75–79%`: Possible
- below `75%`: discarded before rendering and download selection

Blackbird records use status semantics such as `Verified site match` instead of an invented percentage.

## Dependencies and setup stages

The main Theia environment remains free of the heavy worker dependencies.

### Blackbird environment

```text
Update/blackbird/.venv
```

Install the uploaded pinned Blackbird requirements and the worker's small protocol support. The worker must run from the Blackbird root and use temporary output paths.

### InsightFace environment

```text
Update/insightface/.venv
```

Install the uploaded Python package with:

- `onnxruntime-gpu` rather than CPU-only `onnxruntime`;
- OpenCV;
- NumPy;
- SciPy;
- Pillow and the package runtime dependencies;
- one explicitly selected InsightFace model pack.

The selected public pretrained models are restricted by InsightFace to non-commercial research use. The private personal-tool scope must remain documented; commercial distribution requires separate model licensing or a separately licensed model pack.

### Installation sequence

1. Validate Python, NVIDIA driver, and GPU runtime.
2. Create the Blackbird and InsightFace virtual environments.
3. Install dependencies independently.
4. Install and verify the selected InsightFace model.
5. Run Blackbird worker smoke tests.
6. Run InsightFace CPU/GPU detection smoke tests.
7. Initialize the persistent SQLite face index.
8. Wire the workers into Theia and remove Tookie runtime wiring.
9. Run the complete project and worker test suites.

SmartImage remains on its existing .NET/Rdx runtime and is not duplicated in either Python environment.

## Deferred Theia learning layer

After the deterministic pipeline passes, Theia may add local orchestration and explicit preference memory. The model can choose capabilities, select full-image versus face-crop searches, summarize normalized results, and learn from explicit user feedback.

The local memory may contain:

- preferred search providers;
- aliases and username relationships;
- user-approved face labels;
- accepted or rejected result feedback;
- provider reliability observations.

It must not silently retrain Qwen, reveal hidden reasoning, or send search history, embeddings, or images to an external AI service.

## Safeguards and error handling

Every worker returns structured success or failure data. Concise errors are shown in the terminal and detailed diagnostics are written under `var/logs/`.

The system handles:

- missing virtual environments or models;
- CUDA provider initialization failure;
- Blackbird site-list update failures;
- individual site timeouts;
- SmartImage upload/search failures;
- corrupted or changed indexed images;
- worker timeout or malformed JSON;
- cancellation before external submission.

Safeguards include:

- one confirmation before each external image upload or OSINT scan;
- no model-generated shell commands;
- fixed worker executable paths;
- validated usernames, emails, paths, and JSON;
- `shell=False` subprocesses;
- TLS verification enabled;
- local-only face embeddings;
- deletion of temporary face crops after search;
- confidence filtering before rendering;
- explicit CPU/GPU status;
- no external Blackbird AI service.

## Testing and acceptance criteria

The implementation is complete when:

- Blackbird performs username searches through a validated JSON worker;
- email OSINT is exposed through a separate validated action;
- Tookie is no longer used at runtime;
- Blackbird results are normalized, deduplicated, and rendered in Rich;
- InsightFace detects faces and reports the actual execution provider;
- the image-folder index survives restart and correctly handles add/change/delete cases;
- face crops are generated and removed according to policy;
- SmartImage can search the full image and selected face crops after confirmation;
- image and face results below 75% are absent from the rendered result set;
- worker errors, cancellation, and malformed output are handled without crashing chat;
- the existing project test suite and new integration tests pass;
- manual smoke tests work with the uploaded image folder.

Required test groups:

- Blackbird worker protocol and normalization;
- username/email validation;
- InsightFace provider detection;
- persistent index add/update/delete/rebuild;
- face crop generation and cleanup;
- local face similarity ranking;
- SmartImage merge and deduplication;
- confidence-band filtering;
- confirmation, cancellation, timeout, and malformed JSON;
- full existing test suite.

## Licensing and release constraints

The uploaded Blackbird tree contains a GPLv3 license document and the WhatsMyName data source has its own licensing terms. The exact redistribution obligations must be confirmed before releasing a combined distributable.

InsightFace code is MIT-licensed, while the public pretrained model packs are restricted to non-commercial research use. The personal-use scope is part of this design; any commercial or public release requires a separate licensing review.

## Decision

Proceed with isolated Blackbird and InsightFace workers, replace Tookie, maintain a persistent local InsightFace index, use face crops with SmartImage for confirmed external reverse search, filter image confidence below 75%, and defer Theia's explicit local learning layer until the deterministic pipeline is stable.
