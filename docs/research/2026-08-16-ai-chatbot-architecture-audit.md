# Read-only architecture audit: local Rich AI chatbot and OSINT tools

Date: 2026-08-16  
Scope: repository structure, current Python CLI, downloaded llama.cpp/model assets, `Update/SmartImage-4`, `Update/tookie-osint`, and existing research/spec notes.  
Constraint: no application source code was modified.

## Executive decision

The requested product is feasible, but the current repository is not yet an AI-agent application. It is a Python 3.11+ Rich/Typer video search and download CLI. The safest implementation is an orchestration layer in Python:

```text
Rich chat loop
    -> local llama-server (Qwen3.5 HauhauCS, loopback only)
    -> validated structured action plan
    -> confirmation gate for network/filesystem side effects
    -> existing search/download code, SmartImage.Rdx, or isolated Tookie process
    -> normalized result/report rendered by Rich
```

The model should interpret intent, refine search terms, describe an uploaded image, and propose a tool action. Python must own URL/path validation, subprocess arguments, confirmations, timeouts, output parsing, and lifecycle. The model must not receive arbitrary shell access.

The next implementation should be staged. Do not replace the existing menu and production paths in one large change: first prove the local model, then add one controlled tool at a time, then make chat the default launcher.

## Current repository state

### Application entrypoint and CLI

- [`main.py`](../../main.py) inserts `src` on `sys.path` and calls `private_search.app.cli.interactive_menu()`.
- [`main.bat`](../../main.bat) is the Windows launcher.
- [`src/private_search/app/cli.py`](../../src/private_search/app/cli.py) exposes the current Rich/Typer UI: search, direct download, metadata inspection, help, and a menu loop.
- [`pyproject.toml`](../../pyproject.toml) declares Python `>=3.11` and the current dependencies: BeautifulSoup, Requests, Rich, RapidFuzz, Pillow, Typer, and yt-dlp. There is no model client, HTTP chat client, .NET integration, Selenium dependency, or Tookie environment in the main environment.
- Existing application modules are separated into `app`, `search`, `download`, `net`, and `sources`; this is a good seam for adding an `agent`/`integrations` layer without mixing orchestration into site adapters.
- Existing tests cover the current CLI, download, HTTP, source adapters, and search behavior. The existing menu design explicitly describes a simple downloader menu, so the AI-chat change is a product-level redesign rather than a small menu edit. The resulting module layout is documented in [`docs/architecture.md`](../architecture.md).

### Existing notes

[`docs/research/2026-08-16-ai-osint-integration.md`](2026-08-16-ai-osint-integration.md) already establishes the important capability boundary: Qwen is local image understanding and planning, SmartImage is reverse-image search, and Tookie is username/account OSINT. It also recommends treating SmartImage and Tookie as controlled external tools. The older search/download plans are useful for regression constraints, but they do not specify an agent runtime or confirmation protocol.

### The Robin reference tree is a separate application

The ignored `Update/robin` reference tree is not wired into the root package or launcher. It is a Streamlit dark-web OSINT application with its own `requirements.txt`, Docker/Tor entrypoint, investigation JSON storage, and LangChain-based provider selection. Its LLM layer can discover Ollama models through `/api/tags` and llama.cpp/custom OpenAI-compatible models through `/v1/models`, but it does not start the repository's local `llama-server`, import the root Rich/Typer code, or provide a Rich terminal interface. Reusing it directly would therefore import a second application boundary and a Tor/network workflow; the better seam is a reviewed service/tool adapter or a separately maintained application, not an implicit root dependency.

### Downloaded runtime and model assets

The following local assets were found under `var/`:

| Asset | Observed state | Meaning |
|---|---:|---|
| `var/runtime/llama.cpp/b10451/bin/llama-server.exe` | present; `0.1.0-dev`, build `10451` | CPU Windows x64 server binary starts and prints help |
| `Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf` | `2,707,513,696` bytes; SHA-256 `79E28ECACF84E75B6056CF4059636D435AA9EB67795780F7B7DBC7D32A962741` | Main text/model file is complete in size; retain the hash in a local manifest before use |
| `mmproj-Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-BF16.gguf` | `50,331,648` bytes; valid GGUF header observed | Not ready for vision: the official model card lists the projector as 645 MB, so this local file is an incomplete transfer or wrong artifact |
| `q4-tail-1.append` | `15,450,112` bytes | Download-resume residue; not a model input and should be quarantined or removed only after confirming it is not needed for resumption |

The model card describes the selected Q4 file as approximately 2.6 GB and says that the separate `mmproj` vision encoder is required for image/video input. llama.cpp’s official multimodal documentation likewise requires `--mmproj` when loading a local multimodal GGUF. Therefore text chat can be validated now, but the requested uploaded-image workflow is blocked until the projector is completely downloaded and verified. Sources: [HauhauCS model card](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive), [llama.cpp multimodal documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md).

The repository now ignores `/var/`, `/Update/`, and `/image/`. This keeps model/runtime assets, vendor references, downloaded media, and personal inputs out of Git. A future release should maintain a separate manifest with download URLs and hashes rather than committing those artifacts.

## Integration audit

### llama.cpp and model server

The installed binary exposes the required `--model`, `--mmproj`, `--host`, `--port`, `--jinja`, grammar, and chat-template options. The official server documentation describes an OpenAI-compatible chat endpoint, schema-constrained JSON, and tool/function calling. The official multimodal documentation identifies `llama-server`’s OpenAI-compatible chat endpoint as the image-input path. Sources: [llama-server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md), [multimodal documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md).

Recommended startup contract:

1. Resolve executable, model, and projector paths from repository configuration; reject paths outside approved roots.
2. Start `llama-server.exe` bound to `127.0.0.1` on a selected local port, with the exact model and projector paths.
3. Capture stdout/stderr to a temporary diagnostic log that is not part of chat history.
4. Poll a readiness endpoint and perform a small deterministic text completion before accepting user input.
5. Keep the process handle and terminate it in a `finally`/shutdown path, including Ctrl+C and startup failure.
6. Use the OpenAI-compatible chat endpoint from Python, but require a validated JSON action envelope rather than trusting free-form text as a command.

The selected aggressive derivative is not “trained for this program”; it is a general multimodal model derivative. Program-specific behavior must come from the system prompt, tool schemas, examples, validation, and tests. Image understanding does not perform reverse-image search by itself.

### SmartImage-4

The supplied `Update/SmartImage-4` source contains `SmartImage.Lib`, `SmartImage.Rdx`, GUI projects, and a solution. The local Rdx project is an executable targeting `net10.0`. Its source supports file/URL input and structured delimited output with fields such as name, URL, similarity, artist, and site. The official Rdx usage page describes the same CLI boundary and shows file/URL input, engine selection, and output-file options. Source: [SmartImage Rdx usage](https://github.com/Decimation/SmartImage/wiki/%28Rdx%29-Usage).

Current blockers:

- `dotnet --version` reports that no .NET SDK is installed.
- The local project references `FlareSolverrSharp`, `Kantan`, `Kantan.Net`, and `Novus` through HintPaths outside the repository (`..\..\..\VSProjects\...`). Those DLLs are not present in this workspace.
- The local target `net10.0` does not match the upstream README’s older “.NET 6” setup guidance; pin the exact source revision and build requirements before relying on either statement.
- No compiled SmartImage executable is present under the repository.

Recommended boundary: build/publish `SmartImage.Rdx` as a pinned child executable and invoke it with an argument list, never a shell string. Use an allowlisted engine set and delimited output to a temporary file. Disable browser cookies, FlareSolverr, context-menu integration, and completion commands by default. Do not use the deprecated server path. SmartImage’s own README identifies it as a reverse-image-search tool for Windows and its Rdx documentation explicitly supports the CLI shape. Source: [SmartImage README](https://github.com/Decimation/SmartImage/blob/master/README.md).

### Tookie OSINT

The supplied `Update/tookie-osint` source is a standalone Python CLI, not a library. Its entrypoint requires exactly one of `-u/--user` or `-U/--userfile`, supports text/CSV/JSON output, and uses a thread pool for site checks. The official README describes username/account discovery and says the current version is optimized for Python 3.12. The official requirements list `colorama`, `requests`, `argparse`, `selenium`, and `webdriver-manager`. Sources: [Tookie README](https://github.com/Alfredredbird/tookie-osint/blob/main/README.md), [Tookie entrypoint](https://github.com/Alfredredbird/tookie-osint/blob/main/brib.py), [Tookie requirements](https://github.com/Alfredredbird/tookie-osint/blob/main/requirements.txt).

Recommended boundary: use a separate Python 3.12 virtual environment and run Tookie only after an explicit user confirmation. Pass one user-supplied username or a user-selected file, cap threads, set a timeout, write results to a controlled report directory, and parse JSON/CSV as untrusted data. Do not automatically turn a model-generated name, image caption, or guessed identity into a Tookie scan. Tookie’s runtime performs outbound requests to many sites and may use Selenium/browser drivers, so “local” describes the launcher, not the network boundary.

The local copy does not include the upstream license file in its file listing. Before redistribution or installation, preserve and review the upstream license and security guidance; do not treat a copied source directory as a supply-chain-verified dependency.

## Product architecture to implement

### 1. Chat/session layer

Replace the current menu only after the new layer passes tests. Keep the current Typer one-shot commands for compatibility. Add a Rich chat loop with:

- visible startup status for model/server readiness;
- plain text conversation plus an optional image/file attachment command;
- short and detailed response modes;
- a session context containing the last user-uploaded image, last search results, and approved actions;
- a clear `quit`/Ctrl+C path that shuts down the model server.

### 2. Action protocol

Have the model return one of a small, versioned set of actions, for example:

`respond`, `refine_search`, `download_media`, `reverse_image_search`, `username_osint`, and `describe_image`.

Every action needs a strict schema and a Python validator. The validator should normalize URLs, reject non-http(s) network targets where appropriate, restrict local paths to an attachment/download/report directory, cap result counts/threads/timeouts, and reject unknown fields. If the model emits malformed JSON or an unsupported action, show the response as text and do not execute anything.

### 3. Confirmation gate

The model may propose an action; only the user can authorize it. The Rich confirmation panel should show:

- action name and short explanation;
- exact URL, image path, username, or input file;
- external destinations/domains when known;
- output directory and estimated scope;
- tool-specific options such as SmartImage engines or Tookie thread count.

Downloads, reverse-image searches, and Tookie scans should default to “deny unless confirmed.” A confirmation must apply to one concrete validated action, not to all future actions.

### 4. Tool adapters

- Existing search/download adapter: wrap current `search.search`, `search.inspect_direct_url`, and `downloader.download_video`; preserve the current Rich progress and existing tests.
- SmartImage adapter: subprocess wrapper, temporary structured-output file, bounded timeout, exit-code check, CSV parsing, and normalized result table.
- Tookie adapter: subprocess wrapper to the isolated venv, JSON output when possible, bounded execution, report path, and explicit network disclaimer.
- Model adapter: loopback HTTP client for llama-server, with request size limits and no automatic remote fallback.

The model should not be required to perform the actual reverse search. For “do a reverse search on the image I uploaded,” Python should use the attachment directly with SmartImage; the model can choose engines or explain results after the search.

## Concrete next steps, in order

1. **Artifact hygiene.** Decide whether `var/models` and `var/runtime` are ignored or packaged separately. Record the model filename, source URL, runtime build, and SHA-256 in a local manifest. Quarantine the `q4-tail-1.append` residue. Do not delete it until the download workflow confirms it is not needed.
2. **Finish the vision prerequisite.** Resume/download the exact BF16 projector from the selected model repository until its size matches the model card and llama.cpp can load it. Verify the GGUF header and perform a local image prompt smoke test.
3. **Prove text-only llama-server.** Start the server manually with the complete Q4 model on loopback, run a deterministic `/v1/chat/completions` request, and record usable context, CPU/GPU mode, latency, and memory. Do not design production defaults from an unmeasured machine profile.
4. **Resolve SmartImage build inputs.** Install a .NET SDK compatible with the pinned project target, obtain/build the four external local-reference dependencies, or make a separately reviewed project-file change to use reproducible package/project references. Publish only `SmartImage.Rdx`, then run its `--help` and a test image in delimited-output mode.
5. **Isolate Tookie.** Create a Python 3.12 environment outside the main dependency set, install from the pinned source/requirements, run `brib.py --help`, and perform a harmless test username scan with low concurrency. Confirm output parsing and network behavior before exposing it to chat.
6. **Write the agent contract before coding.** Specify action JSON schemas, confirmation text, path/URL policy, tool timeouts, output normalization, error categories, and session attachment behavior. This is the missing design artifact between the current menu spec and implementation.
7. **Implement the model supervisor and client.** Add startup/readiness/shutdown handling and a loopback chat client. Make server failure non-destructive: the app may fall back to the existing non-AI CLI, but it must not silently run a remote model.
8. **Implement one tool at a time.** First `respond` and `refine_search`; then existing download with confirmation; then SmartImage; then Tookie. Keep each adapter behind a narrow interface and add focused tests before wiring it to the model.
9. **Replace the default launcher.** Once the chat loop is stable, make `main.py` start it while retaining `qt search`, `qt download`, and metadata inspection as compatibility commands. Update the help text and README only after the final command behavior is known.
10. **Run integration and lifecycle tests.** Verify startup, readiness failure, malformed model output, confirmation rejection, child-process timeout, Ctrl+C cleanup, no leaked llama-server/SmartImage/Tookie processes, and preservation of all existing tests.

## Blockers and decisions requiring explicit resolution

| Item | Status | Required resolution |
|---|---|---|
| Q4 model | Complete-size local file; hash recorded | Add a manifest and test-load it |
| Vision projector | Blocked; only 50,331,648 bytes locally vs official 645 MB listing | Complete transfer and test-load with `--mmproj` |
| llama.cpp | Available as CPU Windows x64 build | Measure actual performance and choose safe context/thread defaults |
| .NET SDK | Missing | Install compatible SDK or obtain a prebuilt SmartImage Rdx artifact |
| SmartImage dependencies | Missing external DLLs referenced by local HintPaths | Pin and build dependencies, or perform a reviewed project-file portability change |
| Tookie environment | Not installed in main project | Create isolated Python 3.12 environment and pin dependencies |
| Artifact tracking | `var/` is untracked and not ignored | Establish ignore/manifest policy before commits |
| Licensing/provenance | SmartImage source is GPLv3 per prior research; local Tookie copy lacks visible license file | Preserve notices, pin source revisions, and review redistribution terms |
| Tool calling reliability | Not measured for this derivative/model build | Require schema validation and test malformed/ambiguous outputs |
| Network/privacy policy | SmartImage/Tookie send data to third parties | Show destinations and obtain per-action confirmation |

## Verification gates

### Gate A — clean environment

Pass only when the project can locate the runtime and assets from configuration, artifacts are not accidentally tracked, the model hash is recorded, and all missing executable prerequisites are reported clearly.

### Gate B — local model

Pass only when text chat works through loopback llama-server, startup/shutdown leaves no orphan process, and malformed server responses do not execute tools.

### Gate C — vision

Pass only when the complete matching projector loads with the selected Q4 model and a local image produces a bounded description. This gate does not count as reverse-image search.

### Gate D — existing capabilities

Pass only when natural-language search refinement reaches the existing search engine, a direct media link creates a preview and asks for confirmation, and rejection performs no download.

### Gate E — SmartImage

Pass only when the pinned Rdx executable accepts a local image, returns structured output, times out cleanly, and the Rich UI labels engine/source/URL/similarity without presenting a match as identity proof.

### Gate F — Tookie

Pass only when the isolated process accepts a confirmed username, produces parseable output, obeys concurrency/timeouts, and does not run from model-generated identity guesses without another confirmation.

### Gate G — end-to-end chat

Pass only when these scenarios are deterministic:

1. “Download this link” → preview → confirmation → existing downloader.
2. “Search for Bimbo Pmv” → refined query/filter plan → existing search results → optional per-download confirmation.
3. “Reverse search the image I uploaded” → attachment selection → confirmation showing external search → SmartImage results.
4. “Search this username” → confirmation showing username and network scope → Tookie report.
5. “Give me a brief/detailed report” → the same structured results rendered at the requested verbosity.

## Primary sources consulted

- [HauhauCS Qwen3.5 model card](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive)
- [llama.cpp multimodal documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md)
- [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [SmartImage README](https://github.com/Decimation/SmartImage/blob/master/README.md)
- [SmartImage Rdx usage](https://github.com/Decimation/SmartImage/wiki/%28Rdx%29-Usage)
- [Tookie README](https://github.com/Alfredredbird/tookie-osint/blob/main/README.md)
- [Tookie entrypoint](https://github.com/Alfredredbird/tookie-osint/blob/main/brib.py)
- [Tookie requirements](https://github.com/Alfredredbird/tookie-osint/blob/main/requirements.txt)
