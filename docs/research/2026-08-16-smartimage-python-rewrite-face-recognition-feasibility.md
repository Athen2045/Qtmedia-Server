# SmartImage Python Rewrite and `face_recognition` Feasibility

Date: 2026-08-16  
Scope: Research-only evaluation of whether to translate the bundled SmartImage Rdx/C# implementation into Python as a built-in Theia capability, and whether `ageitgey/face_recognition` is suitable for local face detection/encoding/cropping in support of reverse-image search.  
Source policy: primary sources only: local bundled SmartImage source/runtime help, the current Python adapter, official SmartImage GitHub/wiki/docs, official `face_recognition` README/source/PyPI, and official `dlib` README/source/PyPI/docs.

## Executive recommendation

- Do not rewrite SmartImage into Python now. Keep the current subprocess boundary as the production architecture.
- Do not adopt `ageitgey/face_recognition` as a built-in dependency for this repository.
- If we want better person-centric reverse-image search later, do a hybrid spike: keep SmartImage as the network-facing engine fan-out, and test optional local face preprocessing separately behind a feature flag and explicit consent.
- If that spike ever proves worthwhile, evaluate direct `dlib` use or another actively maintained detector/aligner before considering `face_recognition`, because `face_recognition` is a thin wrapper over `dlib`, does not officially support Windows, does not advertise Python 3.12+ support, and adds little beyond what `dlib` already exposes directly.[^fr-readme][^fr-setup][^fr-api][^dlib-docs][^dlib-setup]

## Direct answer

### Should we translate SmartImage into Python as a built-in Theia capability?

No, not at this time.

The current Python side is intentionally narrow: it validates a local file, asks for confirmation, launches SmartImage Rdx in non-interactive delimited-output mode, writes SmartImage state into a temporary `NOVUS_DATA_FOLDER`, and falls back to a local `dotnet` host if Windows application control blocks the self-contained executable.[^local-adapter][^local-tests] That boundary already avoids reimplementing SmartImage's engine fan-out, upload rules, cookie handling, and brittle parsing logic.

The bundled SmartImage source shows that a true Python port would need to absorb:

- 16 search-engine options in `SearchEngineOptions.All`.[^si-engines-enum]
- Multiple upload providers with different limits and behaviors.[^si-upload-options][^si-upload-catbox][^si-upload-litterbox][^si-upload-tmpfiles]
- Mixed request models: some engines use an uploaded URL, some upload the image bytes directly to their own API, and some scrape HTML/DOM or require cookies/FlareSolverr.[^si-query][^si-searchcommand][^si-source-usage][^si-rdx-usage]
- Upstream service drift and unfinished engine code already visible in the vendored tree (`FluffleEngine` says “todo: update to new API”, `ImgOpsEngine` has `NotImplementedException`, `KarmaDecayEngine` is effectively a placeholder, and `BingEngine` says parsing is not feasible “ATM”).[^si-fluffle][^si-imgops][^si-karmadecay][^si-bing]

That is a large parity project, not a small translation.

### Should we use `face_recognition`?

No.

It is useful as a simple demo-friendly wrapper, but it is not a good fit for this repository's Windows-first, Python-3.12+ CI surface:

- The official README still says Windows is not officially supported.[^fr-readme]
- The repository `setup.py` classifiers stop at Python 3.9.[^fr-setup]
- PyPI's latest published release is still `1.3.0` from February 20, 2020.[^fr-pypi]
- Its import path hard-depends on the separate `face_recognition_models` package and tells users to install that from GitHub if import fails.[^fr-api]
- For the underlying heavy lifting it simply calls `dlib` detectors, shape predictors, and encoders.[^fr-api]

If we ever need local face alignment/cropping, the authoritative lower layer is `dlib`, not `face_recognition`. `dlib` is actively released on PyPI, documents Windows support, requires Python `>=3.8`, exposes the CNN detector, the frontal HOG detector, and `get_face_chips()` for aligned crops, and lets build settings be controlled through `DLIB_*` CMake options.[^dlib-pypi][^dlib-setup][^dlib-docs]

## Current repository reality

The current Theia-side integration is already a carefully scoped subprocess adapter:

- `src/private_search/osint/smartimage.py` shells out to SmartImage Rdx with `--interactive false`, `--output-format Delimited`, a fixed delimiter, and a fixed field list, then parses the generated file as untrusted CSV-like output.[^local-adapter]
- It defaults to `TmpFiles` rather than SmartImage's own documented/default `Catbox`, which is a deliberate local policy choice to avoid the upstream default.[^local-adapter][^local-smartimage-help][^si-searchconfig]
- It creates a temporary work directory and temporary SmartImage data folder for each run, which reduces global state and permission coupling.[^local-adapter]
- It already contains a Windows application-control fallback from `SmartImage.exe` to `dotnet SmartImage.dll`.[^local-adapter][^local-runtimeconfig]

That is a strong argument for preserving the current architecture unless we need features the subprocess cannot expose.

## Evidence table

| Topic | Evidence | Implication |
| --- | --- | --- |
| SmartImage engine surface | `SearchEngineOptions.All` includes 16 engines: SauceNao, ImgOps, GoogleImages, TinEye, Iqdb, TraceMoe, KarmaDecay, Yandex, Bing, Ascii2D, RepostSleuth, EHentai, ArchiveMoe, Iqdb3D, Fluffle, and GoogleLens.[^si-engines-enum] | A Python port is a multi-engine reimplementation project, not a wrapper cleanup. |
| SmartImage runtime model | `SearchCommand` has a headless path that uploads/initializes the query, runs searches, and writes delimited output; the current Python adapter is built around exactly that contract.[^si-searchcommand][^local-adapter] | The subprocess path is aligned with upstream design and already production-shaped. |
| Upload behavior is not uniform | `SearchQuery.TryUploadAsync()` uploads local images through a selected upload engine, but several engines still post the file directly (`TraceMoe`, `RepostSleuth`, `GoogleLens`, `Iqdb`, `EHentai`, `Fluffle`, HTML-mode `SauceNao`). Others use `query.Upload.Url`.[^si-query][^si-source-usage] | Rewriting SmartImage means reproducing per-engine request semantics, not just forwarding one hosted URL. |
| Scraping/cookie burden | Official Rdx docs expose `--read-cookies` and `--flaresolverr`; source shows HTML parsing with AngleSharp/XPath and cookie handling in engines like `Ascii2D`, `Yandex`, `GoogleLens`, `EHentai`, `ArchiveMoe`, and `SauceNao`.[^si-rdx-usage][^si-engine-scan][^si-yandex][^si-googlelens][^si-saucenao] | A Python port inherits a high maintenance burden from markup drift, anti-bot changes, and browser-state handling. |
| Some SmartImage engines are already drifting | `FluffleEngine` says “todo: update to new API”; `ImgOpsEngine` has `NotImplementedException`; `KarmaDecayEngine` is effectively stubbed; `BingEngine` comments that parsing is not feasible ATM.[^si-fluffle][^si-imgops][^si-karmadecay][^si-bing] | Upstream itself is carrying service drift. Porting now would copy unstable behavior and create permanent fork debt. |
| Local adapter policy differs from upstream defaults | Bundled SmartImage help and `SearchConfig` show default upload engine `Catbox`; the Python adapter defaults to `TmpFiles`. The local README also documents `TmpFiles` as temporary hosting with 60-minute expiry, consistent with `TmpFilesEngine.DEFAULT_EXPIRY_SEC = 3600`.[^local-smartimage-help][^si-searchconfig][^local-readme][^si-upload-tmpfiles][^local-adapter] | The current wrapper already gives us policy control without rewriting SmartImage internals. |
| SmartImage runtime/platform coupling | Bundled SmartImage source targets `net10.0`, and the framework-dependent runtime config expects `.NET 10.0.0`.[^si-rdx-csproj][^local-runtimeconfig] | Rewriting in Python would remove .NET dependence, but only by taking on much larger functional and maintenance risk. |
| `face_recognition` support posture | Official README says Windows is not officially supported; repo `setup.py` classifiers stop at Python 3.9; PyPI latest is `1.3.0` from 2020-02-20.[^fr-readme][^fr-setup][^fr-pypi] | Poor fit for a repository whose local docs and CI already target Python 3.12, 3.13, and 3.14.[^local-readme][^local-pyproject] |
| `face_recognition` is a thin wrapper over `dlib` | `api.py` imports `dlib`, loads predictor/model files, calls `dlib.get_frontal_face_detector()`, `dlib.cnn_face_detection_model_v1`, `dlib.face_recognition_model_v1`, and computes encodings directly from `dlib` descriptors.[^fr-api] | If we need this capability, direct `dlib` use is the more stable and honest abstraction boundary. |
| `face_recognition` does not add the crop primitive we need most | `face_recognition` exposes locations, landmarks, encodings, and comparisons, while `dlib` documents `get_face_chip()` / `get_face_chips()` for upright aligned crops.[^fr-api][^dlib-docs] | For cropping/alignment, `dlib` is the authoritative API anyway. |
| CUDA/GPU story | `face_recognition` README says the CNN detector needs CUDA for good performance; `dlib` build docs allow CMake/`DLIB_*` configuration and Windows x64 builds.[^fr-readme][^dlib-setup] | GPU helps only for the local face-detector path; it does nothing to reduce SmartImage's network/scraping maintenance. |
| Accuracy/fairness limits | Official `face_recognition` README says the model does not work very well on children. The official wiki says accuracy can be lower across demographic groups and explains that the model quality is limited by uneven training data.[^fr-readme][^fr-accuracy] | Using face encodings as a reverse-search prefilter introduces bias and biometric risk that need explicit product justification. |
| Supply-chain age of model package | `face_recognition_models` latest release is still `0.3.0` from 2017-09-28; its description says the model files are public domain or CC0, while the package metadata is MIT.[^fr-models-pypi] | The dependency stack is old and licensing signals are mixed enough to warrant care, not casual adoption. |

## Architecture comparison

| Option | Pros | Cons | Recommendation |
| --- | --- | --- | --- |
| Keep subprocess | Preserves upstream engine behavior; smallest code surface; isolates .NET/service drift; current adapter already has temp-state isolation and Windows fallback.[^local-adapter][^local-tests] | Requires bundled SmartImage runtime; limited introspection into per-engine internals; still depends on upstream CLI behavior. | Best production choice now. |
| Full Python port | Single language; easier in-process instrumentation; no .NET runtime. | Must reimplement engine fan-out, upload providers, cookies, FlareSolverr, scraping, result normalization, and service drift; license review blocker for code translation. | Not recommended now. |
| Hybrid | Keep SmartImage subprocess for search coverage while adding optional local preprocessing or richer orchestration in Python. | More moving parts than status quo; must validate that preprocessing actually improves person-centric results and does not harm non-face engines. | Best path for any future experimentation. |

## Request/upload behavior findings

These details matter because they define the real scope of any rewrite:

- Official Rdx usage allows a direct image URI, a file path, or piped stdin/binary input, and exposes `--search-engines`, `--priority-engines`, `--upload-engine`, `--read-cookies`, `--flaresolverr`, and structured delimited output flags.[^si-rdx-usage]
- `SearchCommand.InitQueryAsync()` calls `SearchQuery.TryCreateAsync()` and then `Query.TryUploadAsync(Client.UploadEngine)` before running the search.[^si-searchcommand]
- `SearchQuery.TryUploadAsync()` skips upload when the source is already a URL, but uploads local content through the chosen upload engine otherwise.[^si-query]
- Upload providers have different limits: Catbox 200 MB, Litterbox 1 GB, TmpFiles 100 MB with a default 3600-second expiry; Pomf is marked obsolete.[^si-upload-catbox][^si-upload-litterbox][^si-upload-tmpfiles][^si-upload-pomf]
- Engine behavior is mixed:
  - URL-based or URL-friendly: `Yandex`, `TinEye`, API-key `SauceNao`, `GoogleImages`.[^si-yandex][^si-tineye][^si-saucenao][^si-googleimages]
  - Direct file/API upload: `TraceMoe`, `RepostSleuth`, `GoogleLens`, `Fluffle`, `Iqdb`, HTML-mode `SauceNao`, `EHentai`.[^si-tracemoe][^si-repostsleuth][^si-googlelens][^si-fluffle][^si-iqdb][^si-saucenao][^si-source-usage]
  - HTML/DOM parsing and browser-state sensitivity: `Ascii2D`, `Yandex`, `GoogleLens`, `SauceNao`, `ArchiveMoe`, `EHentai`, `Iqdb`.[^si-engine-scan][^si-yandex][^si-googlelens][^si-saucenao]

This is why “translate SmartImage into Python” would become “rebuild a reverse-image meta-client.”

## Licensing findings

### SmartImage

I did not find a repository-root SmartImage license file in the vendored `Update/SmartImage-4` tree, and the official README/wiki pages I inspected describe functionality and usage but do not settle the redistribution terms on their own.[^si-readme][^si-rdx-usage] The vendored tree does include separately licensed dependencies such as `FlareSolverrSharp` and `Novus`, including a GPL text under `Dependencies/Novus/LICENSE`.[^local-license-scan]

Practical conclusion: before translating SmartImage source into Python or shipping a derived in-process port, we should obtain explicit upstream license confirmation for SmartImage itself and review how its vendored dependencies apply.

### `face_recognition`

The `face_recognition` repository is MIT-licensed, and its `setup.py` declares `license="MIT license"`.[^fr-license][^fr-setup]

### `face_recognition_models`

PyPI metadata says the package is MIT, but the package description says the actual models were created by Davis King and are licensed in the public domain or under CC0 1.0 Universal.[^fr-models-pypi]

### `dlib`

`dlib` is under the Boost Software License.[^dlib-pypi][^dlib-setup]

## Windows and Python 3.12 compatibility

### SmartImage

- The bundled SmartImage source and runtime artifacts are clearly aligned to `.NET 10` today.[^si-rdx-csproj][^local-runtimeconfig]
- The current adapter already handles the practical Windows issue we have seen most often: executable policy blocking, via fallback to the framework-dependent host.[^local-adapter][^local-tests]

### `face_recognition`

- Officially unsupported on Windows according to its own README.[^fr-readme]
- Current repository source classifiers stop at Python 3.9.[^fr-setup]
- Current PyPI release is still from 2020 and predates Python 3.12 by years.[^fr-pypi]

### `dlib`

- Officially supports Python `>=3.8`, includes Windows classifiers, and is actively released on PyPI as of March 29, 2026.[^dlib-setup][^dlib-pypi]
- Build requirements are non-trivial: CMake `>=3.17.0`, correct PATH setup, Windows x64 build settings, and optional `DLIB_*` configuration for custom builds.[^dlib-setup]

## CUDA/GPU implications

- SmartImage itself is not a local ML inference system; GPU does not simplify its core burden, which is remote-engine integration and parsing.
- `face_recognition`'s faster/more accurate CNN detector only performs well with CUDA-enabled `dlib`; the README explicitly says GPU acceleration is required for good performance and that the batched detector is useful when using a GPU.[^fr-readme][^fr-api]
- `dlib`'s build system exposes CMake configuration and `DLIB_*` environment-variable control, which is the real lever for CUDA-enabled builds.[^dlib-setup]

Practical implication: GPU is relevant only if we choose to add a local face-detection path. It is not a reason to rewrite SmartImage.

## Privacy and consent risks

The privacy conclusions in this section are partly inference from what the official sources say the software does.

- SmartImage reverse search necessarily sends the selected image, or a hosted derivative of it, to external services. Official Rdx usage documents file/URL input plus upload-engine selection; local code confirms temporary hosting and direct engine uploads both exist.[^si-rdx-usage][^si-query][^si-source-usage]
- `face_recognition` is explicitly about face detection and 128-dimensional face encodings, which are biometric-style identifiers in practice, even if the project does not use that legal phrase.[^fr-api][^fr-accuracy]
- The official accuracy wiki says model quality is shaped by uneven public training data and can vary across groups.[^fr-accuracy]

Product implication:

- Reverse-image search on full images is already sensitive.
- A face-only preprocessing path would make the workflow more explicitly identity-oriented.
- That raises the bar for user consent, documentation, retention rules, and access control.

If we ever add local face preprocessing, it should be:

- opt-in,
- documented as biometric/identity-sensitive,
- disabled by default,
- not persisted unless the user explicitly saves artifacts,
- and never auto-triggered on confidential or intimate images.

## Why `face_recognition` is the wrong dependency even if face preprocessing helps

Even if face cropping later proves useful for some searches, `face_recognition` is still the wrong dependency choice:

1. It is a convenience wrapper over `dlib`, not a distinct maintained engine.[^fr-api]
2. Its official support posture is weaker than `dlib`'s on Windows and modern Python.[^fr-readme][^fr-setup][^dlib-setup][^dlib-pypi]
3. It does not add the crop/align primitive we would most likely want; `dlib.get_face_chips()` is the direct API for that.[^dlib-docs]
4. Its packaging story is stale: current repo source says `1.4.0`, but PyPI still ships `1.3.0` from 2020-02-20.[^fr-setup][^fr-pypi]

So the right conclusion is not “use `face_recognition` carefully.” It is “do not standardize on `face_recognition` here.”

## Risks

| Risk | Severity | Why it matters |
| --- | --- | --- |
| Python-port parity failure | High | SmartImage mixes hosted-URL search, direct engine uploads, HTML scraping, cookie use, and FlareSolverr. A partial port would likely regress engine coverage or reliability.[^si-source-usage][^si-engine-scan] |
| Ongoing scraper drift | High | The vendored SmartImage tree already contains TODOs and incomplete engines, so a Python fork would inherit a permanent maintenance treadmill.[^si-fluffle][^si-imgops][^si-karmadecay][^si-bing] |
| License ambiguity on SmartImage translation | High | I could not confirm a clean repository-root license from the inspected SmartImage materials, and the vendored tree contains separately licensed dependencies.[^local-license-scan] |
| Unsupported face stack on Windows/Python 3.12+ | High | `face_recognition` says Windows is not officially supported, its classifiers stop at 3.9, and PyPI latest is from 2020.[^fr-readme][^fr-setup][^fr-pypi] |
| Biometric/privacy escalation | High | Face encodings and face-only crops push the feature toward identity inference and therefore higher consent and retention requirements.[^fr-api][^fr-accuracy] |
| GPU expectation mismatch | Medium | Users may assume CUDA solves the reverse-search problem, but it only helps the local detector path, not SmartImage's network/search complexity.[^fr-readme][^dlib-setup] |
| Search-quality regression from cropping | Medium | Inference: person-centric crops might help some photo searches, but could remove useful scene/context cues for engines tuned for artwork, memes, or full-image matching. |

## Proposed phased plan

### Phase 0: Stay with the current production boundary

- Keep SmartImage as an external subprocess.
- Keep the current confirmation gate and temporary-workdir behavior.
- Continue using the current fixed delimited-output contract.[^local-adapter]

### Phase 1: Harden the wrapper, not the engine

- Add more adapter-side telemetry and error classification around engine failures, timeouts, and upload-engine selection.
- Optionally surface engine allowlists/denylists in Python config rather than translating engine logic.
- Clarify SmartImage licensing before any deeper bundling or source reuse.

### Phase 2: Run a narrow hybrid experiment

- Only if there is a concrete product need for person-centric reverse search.
- Prototype optional local face detection/cropping in an isolated branch.
- Feed both original image and face-crop variants through the existing SmartImage adapter in controlled tests.
- Measure whether person-centric searches improve without degrading other image categories.

### Phase 3: Choose the preprocessing foundation only after the experiment

- If the hybrid experiment fails, remove it and keep subprocess-only SmartImage.
- If it succeeds, prefer direct `dlib` evaluation over `face_recognition`.
- Keep preprocessing optional and local; keep reverse search itself behind explicit upload consent.

### Phase 4: Revisit a Python-native SmartImage only if all of these become true

- We need deeper engine-by-engine control that the subprocess cannot provide.
- We have explicit license clearance for translation/derivation.
- We accept maintaining scraper drift and anti-bot breakage in Python.
- We have test fixtures for every engine we intend to keep.

At the moment, those conditions are not met.

## Bottom line

SmartImage should remain an external capability, not be translated into Python now. The existing subprocess adapter is already the right architectural seam.

`face_recognition` should not be used as this repository's built-in face stack. If we ever need local face preprocessing, we should validate the product need first and then evaluate direct `dlib` or another actively maintained detector instead of standardizing on an older convenience wrapper.

## Sources

### Local repository sources

[^local-adapter]: [Current SmartImage Python adapter](../../src/private_search/osint/smartimage.py)
[^local-tests]: [Current SmartImage adapter tests](../../tests/test_smartimage.py)
[^local-pyproject]: [Repository Python requirement](../../pyproject.toml)
[^local-readme]: [Repository README](../../README.md)
[^local-runtimeconfig]: [Bundled SmartImage host runtime config](../../var/smartimage-rdx-host/SmartImage.runtimeconfig.json)
[^local-smartimage-help]: [Bundled SmartImage help output](../../var/smartimage-help.txt)
[^local-license-scan]: [Vendored SmartImage dependency licenses present in local tree](../../Update/SmartImage-4)

### Bundled SmartImage source

[^si-searchcommand]: [Bundled SmartImage `SearchCommand.cs`](../../Update/SmartImage-4/SmartImage.Rdx/Commands/Search/SearchCommand.cs)
[^si-rdx-csproj]: [Bundled SmartImage Rdx project file](../../Update/SmartImage-4/SmartImage.Rdx/SmartImage.Rdx.csproj)
[^si-engines-enum]: [Bundled SmartImage search-engine enum](../../Update/SmartImage-4/SmartImage.Lib/Engines/Search/Base/SearchEngineOptions.cs)
[^si-searchconfig]: [Bundled SmartImage `SearchConfig.cs`](../../Update/SmartImage-4/SmartImage.Lib/SearchConfig.cs)
[^si-query]: [Bundled SmartImage `SearchQuery.cs`](../../Update/SmartImage-4/SmartImage.Lib/SearchQuery.cs)
[^si-upload-options]: [Bundled SmartImage upload-engine enum](../../Update/SmartImage-4/SmartImage.Lib/Engines/Upload/Base/UploadEngineOptions.cs)
[^si-upload-catbox]: [Bundled SmartImage `CatboxEngine.cs`](../../Update/SmartImage-4/SmartImage.Lib/Engines/Upload/CatboxEngine.cs)
[^si-upload-litterbox]: [Bundled SmartImage `LitterboxEngine.cs`](../../Update/SmartImage-4/SmartImage.Lib/Engines/Upload/LitterboxEngine.cs)
[^si-upload-pomf]: [Bundled SmartImage `PomfEngine.cs`](../../Update/SmartImage-4/SmartImage.Lib/Engines/Upload/PomfEngine.cs)
[^si-upload-tmpfiles]: [Bundled SmartImage `TmpFilesEngine.cs`](../../Update/SmartImage-4/SmartImage.Lib/Engines/Upload/TmpFilesEngine.cs)
[^si-source-usage]: [Bundled SmartImage engine source-usage scan](../../Update/SmartImage-4/SmartImage.Lib/Engines/Search)
[^si-engine-scan]: [Bundled SmartImage engine implementation scan](../../Update/SmartImage-4/SmartImage.Lib/Engines/Search)
[^si-saucenao]: [Bundled SmartImage `SauceNaoEngine.cs`](../../Update/SmartImage-4/SmartImage.Lib/Engines/Search/SauceNaoEngine.cs)
[^si-googlelens]: [Bundled SmartImage `GoogleLensEngine.cs`](../../Update/SmartImage-4/SmartImage.Lib/Engines/Search/GoogleLensEngine.cs)
[^si-tracemoe]: [Bundled SmartImage `TraceMoeEngine.cs`](../../Update/SmartImage-4/SmartImage.Lib/Engines/Search/TraceMoeEngine.cs)
[^si-tineye]: [Bundled SmartImage `TinEyeEngine.cs`](../../Update/SmartImage-4/SmartImage.Lib/Engines/Search/TinEyeEngine.cs)
[^si-fluffle]: [Bundled SmartImage `FluffleEngine.cs`](../../Update/SmartImage-4/SmartImage.Lib/Engines/Search/FluffleEngine.cs)
[^si-yandex]: [Bundled SmartImage `YandexEngine.cs`](../../Update/SmartImage-4/SmartImage.Lib/Engines/Search/YandexEngine.cs)
[^si-repostsleuth]: [Bundled SmartImage `RepostSleuthEngine.cs`](../../Update/SmartImage-4/SmartImage.Lib/Engines/Search/RepostSleuthEngine.cs)
[^si-iqdb]: [Bundled SmartImage `IqdbEngine.cs`](../../Update/SmartImage-4/SmartImage.Lib/Engines/Search/IqdbEngine.cs)
[^si-googleimages]: [Bundled SmartImage `GoogleImagesEngine.cs`](../../Update/SmartImage-4/SmartImage.Lib/Engines/Search/Other/GoogleImagesEngine.cs)
[^si-bing]: [Bundled SmartImage `BingEngine.cs`](../../Update/SmartImage-4/SmartImage.Lib/Engines/Search/Other/BingEngine.cs)
[^si-karmadecay]: [Bundled SmartImage `KarmaDecayEngine.cs`](../../Update/SmartImage-4/SmartImage.Lib/Engines/Search/Other/KarmaDecayEngine.cs)
[^si-imgops]: [Bundled SmartImage `ImgOpsEngine.cs`](../../Update/SmartImage-4/SmartImage.Lib/Engines/Search/Other/ImgOpsEngine.cs)

### Official SmartImage sources

[^si-readme]: [Official SmartImage README](https://raw.githubusercontent.com/Decimation/SmartImage/v4/README.md)
[^si-rdx-usage]: [Official SmartImage `(Rdx) Usage` wiki](https://github.com/Decimation/SmartImage/wiki/%28Rdx%29-Usage)

### Official `face_recognition` sources

[^fr-readme]: [Official `face_recognition` README](https://raw.githubusercontent.com/ageitgey/face_recognition/master/README.md)
[^fr-setup]: [Official `face_recognition` `setup.py`](https://raw.githubusercontent.com/ageitgey/face_recognition/master/setup.py)
[^fr-api]: [Official `face_recognition` `api.py`](https://raw.githubusercontent.com/ageitgey/face_recognition/master/face_recognition/api.py)
[^fr-license]: [Official `face_recognition` LICENSE](https://raw.githubusercontent.com/ageitgey/face_recognition/master/LICENSE)
[^fr-pypi]: [Official `face_recognition` PyPI project page](https://pypi.org/project/face-recognition/)
[^fr-models-pypi]: [Official `face_recognition_models` PyPI project page](https://pypi.org/project/face_recognition_models/)
[^fr-accuracy]: [Official `face_recognition` accuracy wiki](https://github.com/ageitgey/face_recognition/wiki/Face-Recognition-Accuracy-Problems)

### Official `dlib` sources

[^dlib-setup]: [Official `dlib` `setup.py`](https://raw.githubusercontent.com/davisking/dlib/master/setup.py)
[^dlib-pypi]: [Official `dlib` PyPI project page](https://pypi.org/project/dlib/)
[^dlib-docs]: [Official `dlib` Python API documentation](https://www.dlib.net/python/)
