# Blackbird + InsightFace implementation research

Date: 2026-08-16  
Status: Research-only sidecar for the approved design  
Audience: Implementers of Theia's Windows terminal application

## Scope and conclusion

This report verifies the approved Blackbird replacement and InsightFace face-index design against the uploaded source trees and primary upstream documentation. It does not change production source, tests, dependency files, or existing documentation.

The design is feasible, but it is not a drop-in integration:

- Blackbird must remain an isolated subprocess. Its current CLI is interactive, writes JSON to a file, uses relative paths derived from `os.getcwd()`, and includes an external AI path that must remain disabled.
- The Blackbird worker needs a staging or wrapper strategy before it can safely support concurrent Theia requests. Merely setting `cwd` to a temporary directory breaks its relative data/assets assumptions; merely running from the repository root causes shared logs/results and filename collisions.
- InsightFace's Python package is suitable for the local detection/embedding worker. The uploaded package is `1.0.1`, uses ONNX Runtime, and supports CUDA through `CUDAExecutionProvider`. The worker must install the GPU ONNX Runtime package explicitly and verify the provider at runtime.
- InsightFace code is MIT-licensed, but the public pretrained model packs are restricted to non-commercial research use. The current design is acceptable for a private personal tool; public or commercial distribution is a release blocker until the model license is resolved.
- The persistent index should be SQLite-owned by one worker process with short transactions and WAL enabled. Embeddings belong in SQLite BLOB columns, not in the JSON worker protocol.
- The approved 75% display threshold is a product filtering rule, not a calibrated probability. SmartImage provider scores, InsightFace embedding similarity, and Blackbird `FOUND` status must remain semantically distinct.

## Sources inspected

Primary sources used:

- [InsightFace repository](https://github.com/deepinsight/insightface)
- [InsightFace Python package README](https://raw.githubusercontent.com/deepinsight/insightface/master/python-package/README.md)
- [InsightFace Python package setup.py](https://raw.githubusercontent.com/deepinsight/insightface/master/python-package/setup.py)
- [Blackbird repository](https://github.com/p1ngul1n0/blackbird)
- [Blackbird upstream HTTP client](https://raw.githubusercontent.com/p1ngul1n0/blackbird/main/src/modules/utils/http_client.py)
- [Blackbird upstream list operations](https://raw.githubusercontent.com/p1ngul1n0/blackbird/main/src/modules/whatsmyname/list_operations.py)
- [Blackbird GPLv3 license](https://raw.githubusercontent.com/p1ngul1n0/blackbird/main/docs/LICENSE)
- [WhatsMyName repository](https://github.com/WebBreacher/WhatsMyName)
- [WhatsMyName data license](https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/LICENSE.md)
- [ONNX Runtime installation documentation](https://onnxruntime.ai/docs/install/)
- [ONNX Runtime CUDA execution provider documentation](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)
- [Python `subprocess` documentation](https://docs.python.org/3/library/subprocess.html)
- [Python `json` documentation](https://docs.python.org/3/library/json.html)
- [Python `sqlite3` documentation](https://docs.python.org/3/library/sqlite3.html)
- [SQLite WAL documentation](https://sqlite.org/wal.html)
- [SQLite transaction documentation](https://sqlite.org/lang_transaction.html)

Local sources inspected:

- Current architecture: [`docs/architecture.md`](../architecture.md)
- Blackbird and InsightFace reference trees: ignored local `Update/` material
- [Current project metadata](../../pyproject.toml)
- Current Blackbird adapter: [`src/private_search/osint/blackbird.py`](../../src/private_search/osint/blackbird.py)
- [Current SmartImage adapter](../../src/private_search/osint/smartimage.py)

## Local baseline

The main project requires Python `>=3.11` and intentionally does not currently depend on Blackbird, InsightFace, ONNX Runtime, OpenCV, or SQLite extensions. The existing OSINT seam is a confirmation-gated subprocess adapter; the Tookie adapter validates input, uses `shell=False`, applies a timeout, and parses a JSON file after the child exits.

That seam is the right shape for both new capabilities. The worker interface should stay small and deep:

```text
Theia action
  -> validated request JSON on stdin
  -> one fixed worker process
  -> one validated response JSON on stdout
  -> diagnostics only on stderr
```

The worker should own provider-specific setup, parsing, retries, and normalization. Theia should own confirmation, executable paths, timeouts, protocol validation, rendering, and cleanup.

## Blackbird findings

### Runtime and version constraints

The uploaded Blackbird tree has a pinned `requirements.txt`, but no `pyproject.toml`, `setup.py`, or explicit application version. Its dependency snapshot includes `aiohttp==3.12.13`, `requests==2.32.4`, `rich==14.0.0`, `python-dotenv==1.1.1`, `Pillow==11.3.0`, and related packages. Those pins describe the uploaded snapshot, not a long-term compatibility guarantee.

The upstream README exposes username and email CLI modes and describes a WhatsMyName-backed search across more than 600 platforms. The current upstream repository describes the dataset as 700+ sites, so the site count is not a stable contract. [Blackbird README](https://github.com/p1ngul1n0/blackbird) [WhatsMyName README](https://github.com/WebBreacher/WhatsMyName)

The worker should use a dedicated environment such as `var/tools/blackbird/.venv`, install only the selected pinned requirements, and run from a fixed absolute root. Do not add Blackbird dependencies to the main THEIA environment.

### It does not provide stdout JSON today

Blackbird's `--json` flag writes a report file through `saveToJson`; it does not turn the terminal into a clean JSON stream. The main script also prints Rich status, prompts for its optional AI path, performs the site-list update, and then runs username/email searches. Therefore the worker cannot safely call the CLI and run `json.loads(completed.stdout)`.

The worker protocol should instead be:

1. Validate one operation and one input in Theia.
2. Create a unique per-request staging directory.
3. Run Blackbird with `--username` or `--email`, `--json`, `--no-update` or an explicitly controlled update mode, and no `--ai`, `--dump`, `--csv`, or `--pdf` flags.
4. Capture stdout/stderr only as diagnostics.
5. Locate the single expected JSON export, parse it, validate its shape, normalize records, and delete the staging output.

The current CLI derives result names from the input and date. Two requests for the same input on the same day can collide if they share the same output tree. This is a direct conflict with the approved design's “temporary output paths” requirement and must be solved with a staging copy or an upstream-compatible output-path change before concurrency is enabled.

### Current working-directory behavior is a real integration conflict

The uploaded `src/config.py` constructs data and log paths with `os.getcwd()`. The CLI also expects relative `assets/` paths, while export code writes results under a path relative to its own source tree. Running with `cwd` equal to Theia's project root is unsafe because it couples the worker to the caller's working directory. Running with `cwd` equal to a blank temporary directory is also unsafe because `data/`, `assets/`, and fonts are absent.

The implementation must choose one of these explicit approaches:

- create a per-run staging tree containing the required Blackbird source/data/assets and run from that tree;
- make a narrowly scoped worker-side wrapper that supplies stable paths and then reads the generated report; or
- refactor Blackbird's path handling and add a deterministic output-path option, preserving the upstream license notices.

The first option offers the strongest isolation but copies or links mutable data. The third option gives the cleanest long-term interface but is a source modification and therefore needs a separate implementation decision.

### TLS verification is disabled in the uploaded code

Both the sync and async HTTP helpers pass `verify=False` / `ssl=False` and suppress the related warnings in the uploaded tree. The same behavior is present in the current upstream HTTP client. [Blackbird HTTP client](https://raw.githubusercontent.com/p1ngul1n0/blackbird/main/src/modules/utils/http_client.py)

This directly conflicts with the approved design's TLS-hardening requirement. The worker must not be marked production-ready until certificate verification is enabled, a deliberate CA/proxy configuration is defined, and tests cover certificate failures. A proxy setting is not a reason to disable verification.

### WhatsMyName update behavior

WhatsMyName is a JSON dataset: each site entry describes the URL and response markers used to decide whether a username exists. The project explicitly separates this data from the checkers and notes that profile URLs, response codes, and page content change over time. [WhatsMyName “How It Works”](https://github.com/WebBreacher/WhatsMyName)

The uploaded Blackbird updater downloads `wmn-data.json`, compares a hash, and writes the new JSON directly to the local path. A robust worker should:

- download to a temporary file;
- parse the complete JSON;
- validate the expected top-level schema and site fields;
- atomically replace the cache only after validation;
- retain the last known-good cache when the network or schema check fails;
- serialize refreshes so two workers cannot overwrite the same cache concurrently.

The dataset is licensed CC BY-SA 4.0. [WhatsMyName license](https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/LICENSE.md) The Blackbird code is GPLv3 in the inspected repository. [Blackbird license](https://raw.githubusercontent.com/p1ngul1n0/blackbird/main/docs/LICENSE) These are separate obligations and must both be carried into any distributable package. This is a release concern, not a reason to prevent private local use.

### Blackbird's external AI must stay disabled

The upstream CLI includes `--ai` and `--setup-ai`, and its README describes sending site names to a hosted AI feature. [Blackbird README](https://github.com/p1ngul1n0/blackbird) The approved design explicitly keeps Theia local and excludes Blackbird's external AI path. The worker must never pass `--ai` and must not import or initialize the AI modules.

## InsightFace findings

### Package and model version

The uploaded Python package reports version `1.0.1`. Its README says that the package uses ONNX Runtime from InsightFace `>=0.2`, installs CPU `onnxruntime` by default, and requires manually installing `onnxruntime-gpu` for GPU inference. [InsightFace package README](https://raw.githubusercontent.com/deepinsight/insightface/master/python-package/README.md)

The package's `setup.py` lists broad, unpinned base requirements including `numpy`, `onnx`, `onnxruntime`, `opencv-python`, `tqdm`, `requests`, `scipy`, and `scikit-image`. The uploaded top-level `Update/insightface/requirements.txt` is not a complete runtime lockfile; it only lists build-oriented requirements such as Cython, CMake, and NumPy. [InsightFace setup.py](https://raw.githubusercontent.com/deepinsight/insightface/master/python-package/setup.py)

Do not install both CPU and GPU ONNX Runtime distributions in the same worker environment. Select and lock one compatible GPU package after checking the installed NVIDIA driver, CUDA runtime, and cuDNN major version.

### Windows and CUDA requirements

ONNX Runtime's official installation documentation states that Windows builds require the Visual C++ 2019 runtime. CUDA execution also requires compatible CUDA and cuDNN libraries, with their `bin` directories available on `PATH`. [ONNX Runtime installation](https://onnxruntime.ai/docs/install/)

The CUDA provider documentation says CUDA minor-version compatibility does not remove the cuDNN major-version requirement: cuDNN 8 and cuDNN 9 are not interchangeable. It also documents that current GPU packages use CUDA 12.x as the default line, while older CUDA 11 packages require a separate installation source. [ONNX Runtime CUDA provider](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)

The setup stage must therefore record:

- Python interpreter version and architecture;
- `onnxruntime-gpu` version;
- visible execution providers;
- NVIDIA driver version;
- CUDA major/minor line;
- cuDNN major version;
- whether the Visual C++ runtime is available.

The worker must report the actual provider from ONNX Runtime after model initialization. “CUDA requested” is not evidence that CUDA was used. If initialization falls back to CPU, Theia must display a degraded-mode status instead of claiming GPU execution.

### Model download and license gate

InsightFace's README says public pretrained model packs, including automatically downloaded and manually downloaded packs, are available for non-commercial research purposes only. The repository states that code is MIT-licensed but model packs and training data have separate restrictions. [InsightFace repository license notice](https://github.com/deepinsight/insightface) [InsightFace package license notice](https://raw.githubusercontent.com/deepinsight/insightface/master/python-package/README.md)

The worker should not silently download a model during a normal image search. Setup should explicitly select a model pack, record its name and checksum, show its license, and fail clearly if the model is missing. For a private personal tool, the approved design's non-commercial scope is consistent with the published model restriction. A public release, hosted service, or commercial distribution requires a separately licensed model or written permission.

The optional GUI and `face3d` extras are not needed for the worker. Avoid installing `insightface[gui]` or compiling the optional Cython/C++ extension unless a later requirement specifically needs them.

### Face semantics

`FaceAnalysis` detects faces and can attach landmarks and recognition embeddings. The result is useful for local similarity search, cropping, clustering, and consistent matching across the image folder. It does not establish a person's real-world identity, and an embedding match is not a calibrated probability.

The approved word “tracking” should be implemented as stable local indexing and similarity/clustering. Use neutral labels such as `face_id`, `source_image`, `embedding_model`, and `match_score`; do not render an embedding score as “this is definitely person X.” Face embeddings and crops should remain local unless the user confirms an external SmartImage submission.

## Worker protocol and process safety

### JSON framing

Python's JSON module serializes and parses values, but it does not define a transport framing protocol. [Python JSON documentation](https://docs.python.org/3/library/json.html) For one request per process, use one bounded JSON object on stdin and one bounded JSON object on stdout. For a long-lived worker, use newline-delimited JSON with exactly one request or response per line, or use a length-prefixed protocol.

The response envelope should be small and explicit:

```json
{
  "ok": true,
  "operation": "face_search",
  "provider": "insightface",
  "provider_runtime": "CUDAExecutionProvider",
  "results": [],
  "warnings": []
}
```

Rules:

- stdout is protocol-only;
- logs and progress go to stderr or a controlled local log file;
- reject trailing non-whitespace data;
- cap request and response sizes;
- validate required keys and types before use;
- never accept an executable path or shell fragment from model-generated JSON;
- keep `shell=False` and pass an argument list to `subprocess.Popen`/`run`.

Python's subprocess documentation confirms that `shell=True` is unnecessary for console executables on Windows and carries additional security considerations. [Python subprocess security guidance](https://docs.python.org/3/library/subprocess.html)

### Lifecycle choice

InsightFace model initialization is expensive and should not occur for every image. A persistent InsightFace worker gives better latency and model locality, but it requires a supervisor, request timeout, crash restart, and a queue. A per-request process is simpler and safer but will repeatedly load the model and may thrash GPU memory.

Recommended compromise:

- one long-lived InsightFace worker per Theia process;
- one GPU inference queue with bounded depth;
- one writer/owner for SQLite;
- restart the worker after malformed protocol output, provider failure, or memory pressure;
- Blackbird remains a bounded per-request subprocess because it is network-bound and CLI-oriented.

## Persistent SQLite index

SQLite is appropriate for a single-user local index. Use separate connections per process; do not pass a live connection or cursor between workers. Python documents connections as the object that owns transaction control and cursors. [Python sqlite3 documentation](https://docs.python.org/3/library/sqlite3.html)

Suggested logical tables:

```text
images
  id, canonical_path, file_size, mtime_ns, content_hash, width, height,
  model_name, model_version, indexed_at

faces
  id, image_id, face_number, bbox_json, landmarks_json,
  crop_path, embedding_blob, embedding_dimension, detection_score

index_meta
  key, value
```

Suggested indexes and invariants:

- unique `(canonical_path, model_name, model_version, face_number)`;
- index `images(content_hash, model_name, model_version)`;
- index `faces(image_id)`;
- normalize embeddings before storing or comparing;
- store vector dimensions and model identifiers beside every embedding;
- do not compare embeddings generated by different model versions without an explicit migration;
- keep crop files derived and disposable, not the source of truth.

Use a transaction for each image refresh: upsert the image metadata, replace its face rows, then commit. On failure, roll back the entire image refresh so an image never has half of its old faces and half of its new faces. SQLite transactions are atomic units and automatically begin around database access when no explicit transaction is active. [SQLite transaction documentation](https://sqlite.org/lang_transaction.html)

WAL mode is useful because readers can proceed while a writer appends changes, but SQLite still permits only one writer at a time. [SQLite WAL documentation](https://sqlite.org/wal.html) Therefore the design should not launch multiple independent index writers. The InsightFace worker should serialize writes, keep write transactions short, and run checkpoints/maintenance deliberately so a long-lived reader cannot keep the WAL growing.

### Index refresh performance

The worker should avoid hashing and re-embedding every file on every request:

1. Enumerate supported files deterministically.
2. Compare canonical path, size, and modification time to the index.
3. Hash only new or changed files, or when a collision-sensitive mode requires it.
4. Detect and embed only changed files.
5. Remove rows and derived crops for deleted files in one transaction.
6. Rebuild when model name/version or embedding dimension changes.

Keep the model loaded once, batch image work where the package permits it, and measure image latency, GPU utilization, peak VRAM, SQLite write time, and cache-hit rate before optimizing further. The 75% display policy should be tested against a labeled local sample; it should not be used as a claim of statistical accuracy.

## Conflicts with the approved design

| Approved statement | Finding | Required resolution |
|---|---|---|
| Blackbird is an isolated JSON worker | Current `--json` is a file export and stdout is Rich text | Add a staging/wrapper protocol; do not parse stdout as JSON |
| Worker runs from Blackbird's own root and uses temporary output | Blackbird resolves data/log paths from `os.getcwd()` and result paths can collide | Use a per-run staged root or refactor path/output handling before concurrency |
| TLS verification is enabled | Uploaded and current upstream HTTP helpers disable it | Harden the worker and test certificate failures before integration |
| WhatsMyName cache is refreshed locally | Current updater writes downloaded JSON directly | Validate, write atomically, retain last-known-good data, serialize refreshes |
| InsightFace uses ONNX Runtime GPU | Package setup installs CPU `onnxruntime` unless replaced | Install one pinned GPU distribution and verify actual providers |
| InsightFace is a persistent local index | Public model packs have non-commercial research restrictions | Keep current scope private/non-commercial or obtain a licensed model |
| Results are rated 75% and above | Provider scores are not comparable probabilities | Treat bands as UI filtering heuristics and label score provenance |
| Theia stays local | Blackbird has an optional hosted AI path | Never pass `--ai`; exclude its AI modules from the worker path |

These are solvable engineering or release gates. None requires translating SmartImage into Python or adding a network API server.

## Setup stages and dependencies

1. **Release and license gate**
   - Keep the first build private and non-commercial.
   - Preserve Blackbird GPLv3 notices and WhatsMyName CC BY-SA attribution/share-alike obligations.
   - Record the selected InsightFace model pack and its non-commercial research restriction.

2. **Blackbird environment**
   - Create `var/tools/blackbird/.venv` with the selected pinned requirements.
   - Keep the external AI feature disabled.
   - Decide between a staged-root wrapper and a path/output refactor.
   - Enable TLS verification and add schema-validated atomic WMN updates.

3. **InsightFace environment**
   - Create `var/tools/insightface/.venv`.
   - Install the local `python-package` at the inspected version `1.0.1`.
   - Install exactly one compatible `onnxruntime-gpu` distribution plus the package's runtime dependencies.
   - Verify Visual C++ runtime, NVIDIA driver, CUDA, cuDNN, and provider availability.
   - Explicitly install or stage one licensed model pack; do not rely on an unreviewed first-run auto-download.

4. **Protocol workers**
   - Define request/response schemas and size limits.
   - Keep stdout protocol-only and stderr diagnostic.
   - Use fixed absolute interpreter/script paths, explicit `cwd`, `shell=False`, timeouts, cancellation, and restart behavior.

5. **Face index**
   - Create SQLite schema and migrations.
   - Enable WAL and a busy timeout.
   - Make one worker the sole writer.
   - Store embeddings as model-tagged BLOBs and crops as disposable derived files.

6. **Theia seam**
   - Replace the Tookie adapter with a Blackbird adapter without changing the confirmation gate.
   - Add separate `email_osint` and `face_search` actions.
   - Keep SmartImage as the external reverse-search adapter and feed it only user-confirmed original images or temporary face crops.

7. **Verification**
   - Test Blackbird protocol, staging, TLS failure, update rollback, username/email validation, timeouts, and malformed JSON.
   - Test InsightFace CPU/GPU provider reporting, model absence, face detection, crop cleanup, index restart, add/change/delete, model migration, and SQLite contention.
   - Benchmark cold start versus warm worker, cache hits versus misses, GPU versus CPU, and one versus multiple detected faces.

## Final recommendation

Proceed with the approved architecture, but treat the following as mandatory gates before implementation is declared complete:

1. Blackbird needs a deterministic staged-root/file-output adapter; it is not a stdout JSON worker today.
2. Blackbird TLS verification must be fixed before it is trusted with OSINT requests.
3. InsightFace must use a pinned GPU ONNX Runtime environment and report the actual provider.
4. The model license must remain visible and restrict the initial build to private, non-commercial use.
5. SQLite writes must be serialized by the InsightFace worker, with atomic per-image refresh transactions.
6. Theia must preserve provenance and semantics for scores rather than presenting every score as an accuracy probability.

No production changes were made during this research pass.
