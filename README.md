# Qt-Downloader

Qt-Downloader is a local terminal application for searching configured video
sites, inspecting candidate links with [yt-dlp](https://github.com/yt-dlp/yt-dlp),
deduplicating results by title and available quality, and downloading a selected
video. Runtime data stays on the local machine.

## Features

- Concurrent searches across the configured site adapters.
- Keyword-based source routing: `porn` searches XHamster, XVideos, YouJizz,
  SpankBang, TNAFlix, PMVHaven, and YouPorn; `youtube` searches YouTube.
- The Rich chatbot does not let the model invent filters, exclusions, or view
  thresholds; it searches the selected sources directly.
- URL and title deduplication before and after yt-dlp inspection.
- Persistent SQLite inspection cache to avoid reprocessing known URLs.
- Progressive result display and interactive download selection.
- Optional Kitty thumbnail preview before downloading a selected result.
- `q` cancellation during an active download.
- Optional integration with a self-hosted [Lustpress](https://github.com/sinkaroid/lustpress) instance.

## Requirements

- Python 3.11 or newer.
- FFmpeg, including `ffprobe`, available on `PATH` for reliable media
  inspection and stream merging.
- Network access to the sites and services you choose to query.

On macOS, install FFmpeg with Homebrew:

```bash
brew install ffmpeg
```

On Windows, install FFmpeg with `winget` from PowerShell:

```powershell
winget install Gyan.FFmpeg.Shared
```

Restart PowerShell after installation, then verify `ffmpeg -version` and
`ffprobe -version` work.

## Installation

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

On Windows PowerShell, use:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### Optional OSINT worker setup

Blackbird and InsightFace stay out of the main project environment. Their setup
scripts create isolated worker virtual environments under `Update/blackbird/.venv`
and `Update/insightface/.venv`.

On Windows PowerShell:

```powershell
.\scripts\setup_blackbird.ps1
.\scripts\setup_insightface.ps1
```

`setup_blackbird.ps1` installs the uploaded Blackbird requirements only. The
application keeps Blackbird list updates disabled by default with
`PRIVATE_SEARCH_BLACKBIRD_UPDATE_SITES=0`; enable updates only when you want to
refresh its site list deliberately.

`setup_insightface.ps1` installs the uploaded `python-package` into its own venv,
pins `onnxruntime-gpu==1.27.0`, and reports whether
`CUDAExecutionProvider` is available or whether the worker would run in explicit
CPU degraded mode. The script does not download model weights.

If you want InsightFace model weights later, do that as a separate explicit step.
The uploaded package README states that the provided pretrained model packs are
for non-commercial research use only. Manual placement is the safest option:
unzip the licensed model pack under `~/.insightface/models/<model_name>/`.
If you explicitly want the library's downloader, run it yourself from the
InsightFace worker venv and expect a network download:

```powershell
.\Update\insightface\.venv\Scripts\python.exe -m insightface.commands.insightface_cli model.download buffalo_l
```

## Usage

After installing (`python -m pip install -e ".[dev]"`), the `qt` command is
available:

```bash
qt search "video title"
qt download https://example.com/video-page
```

On Windows, the easiest path is to double-click `main.bat` or run it from
PowerShell:

```powershell
.\main.bat
```

This opens the Rich AI chatbot and uses the project virtual environment
automatically; activation is not required. The chatbot starts the local
llama.cpp server for the session and can route natural-language requests to
the existing search and download tools. Its assistant identity is Theia: a
sharp, concise, cheeky security-analyst guide with dry wit. She does not use
flirtation, emojis, or filler. Use `/about` to see the active model and the
application safeguards. Use these local commands:

```text
/about            Show Theia, model, and safeguards
/help             Show chat commands
/quit             Exit and stop the local model
```

After a search, the chatbot displays numbered results and asks
`Download result [1-N]`. Enter or `q` skips downloading; selecting a number
routes that result through the normal confirmation prompt.

For reverse-image search, place candidate files anywhere under the project `image` folder.
The chatbot scans that folder recursively when a reverse-image action needs a
local file. With one supported file it auto-selects it; with
multiple matches it shows a numbered Rich picker in discovery order. Theia
keeps the confirmation step after selection because SmartImage uploads the file
externally. Kitty-optional previews are shown during multi-image selection when
the terminal supports them; text-only terminals keep the same picker without
blocking the workflow.

In the chatbot, include a source keyword when you want a specific search
scope, for example `Search porn 'Bimbo PMV'` or `Search youtube 'L vs
Epistein'`. The keyword is removed from the title query before the selected
site adapters run. A search without a source keyword keeps the adult-source
scope for compatibility with the existing downloader.

`qt search` shows matching results in a table. Select a result to view its
metadata and, when running inside Kitty, its thumbnail. Type `r` after the
preview to choose another result, `y` to download it, or press Enter to skip.
The provider search runs only once while you move between results. Pass
`--direct-url <url>`
without a query to inspect a single URL with yt-dlp; inspection mode never
downloads. Use `--no-prompt` when running a search from a script. `qt download
<url>` downloads a direct video URL immediately, showing a live progress bar.

Kitty preview mode downloads and caches only the selected thumbnail under
`var/cache/thumbnails/`. It is optional; text-only terminals continue to show
the thumbnail URL instead.

The console commands remain available for advanced or scripted use:

```bash
private-search "video title"
private-download https://example.com/video-page
```

`main.bat` is the supported Windows launcher; it opens the chatbot with the
project virtual environment automatically, so activation is not required.

Downloads are saved under `var/downloads/`. Enter `q` and press Return when
prompted during a download to request cancellation; press `Ctrl+C` to
interrupt the application.

For sources that provide HLS or DASH fragments, downloads use four concurrent
fragments by default, retry transient HTTP/fragment failures five times, and
wait up to 60 seconds for a stalled socket. Adjust this conservatively with
`PRIVATE_SEARCH_CONCURRENT_FRAGMENTS` (capped at 8). An optional
`PRIVATE_SEARCH_HTTP_CHUNK_SIZE` such as `10M` enables yt-dlp HTTP chunking;
leave it unset unless the source benefits from it.

Slow or unstable CDNs can be given more time with
`PRIVATE_SEARCH_DOWNLOAD_TIMEOUT`; `PRIVATE_SEARCH_DOWNLOAD_RETRIES` controls
the bounded retry count. The project includes `curl-cffi` so yt-dlp can use
browser impersonation where a site requires a browser-like TLS fingerprint.

## Search behavior

Search is federated across the configured site adapters. The adapters retrieve
result pages concurrently, then the program filters and ranks candidates
locally using Unicode-aware token matching, exact phrase and token coverage,
and bounded fuzzy similarity before expensive yt-dlp inspection. Inspected
results are cached in SQLite and deduplicated by normalized title.

## Optional Lustpress integration

Point the search interface at a local Lustpress REST service before starting it:

```bash
export LUSTPRESS_BASE_URL=http://localhost:3000
private-search
```

Lustpress can supplement the built-in adapters for supported sites. It does not
replace yt-dlp or the direct-link downloader. The service must be configured and
running separately.

## Runtime data and configuration

- `var/cache/search.sqlite3` stores inspection results.
- `var/downloads/` stores downloaded media.
- `var/face-index.sqlite` stores the local InsightFace embedding index.
- `var/face-crops/` stores temporary or retained face crops.
- `.env.example` documents optional environment settings.

### Local AI runtime

The project manages the downloaded llama.cpp server automatically through
`private_search.ai.runtime`. By default it uses the Qwen GGUF model, vision
projector, and the CUDA-enabled Windows `llama-server.exe` under `var/`. The
runtime passes `--device CUDA0 --gpu-layers 999` when that build is installed,
so the model and projector are offloaded to the first NVIDIA GPU. Override
paths or limits with the `PRIVATE_SEARCH_LLM_*` variables in `.env.example`.
The server binds to `127.0.0.1`, exposes a local health endpoint, and is
stopped when the chat session exits. The local client and action validator reject non-loopback
endpoints, malformed JSON, unknown actions, unsafe URLs, and missing
action-specific fields. The existing search and download commands remain
unchanged. Side-effecting actions pass through a Rich confirmation service and
fixed Python adapters. SmartImage Rdx is invoked as a separate process in
non-interactive delimited-output mode after confirmation; its results are
rendered in a terminal table. Blackbird username and email OSINT run in an
isolated subprocess and stay confirmation-gated. The model-to-tool
orchestrator keeps bounded history.

### Blackbird username and email OSINT

Blackbird replaces the old Tookie worker for username and email lookups. The
Theia tool layer sends one explicit username or email into the isolated
Blackbird worker, then renders normalized site hits back in chat after
confirmation. The worker interpreter, root, timeout, thread count, and optional
site-list refresh policy are controlled by `PRIVATE_SEARCH_BLACKBIRD_*`.

Blackbird is networked OSINT, not an offline corpus. Results depend on the
current state of the upstream sites and the packaged Blackbird list data. If
you want to refresh the list data, set `PRIVATE_SEARCH_BLACKBIRD_UPDATE_SITES=1`
for a deliberate run, then switch it back off for routine use.

### SmartImage and InsightFace reverse-image search

The setup builds and publishes only `Update/SmartImage-4/SmartImage.Rdx`, not
the SmartImage GUI. The default published executable is
`var/smartimage-rdx/SmartImage.exe`. The launcher sets `NOVUS_DATA_FOLDER` to a
temporary writable directory for each scan so SmartImage's cache does not
depend on the user's global application-data permissions. Override the
executable or timeout with `PRIVATE_SEARCH_SMARTIMAGE_RDX` and
`PRIVATE_SEARCH_SMARTIMAGE_TIMEOUT`. If Windows application control blocks the
self-contained executable, the adapter automatically falls back to the
framework-dependent Rdx build in `var/smartimage-rdx-host/`, launched by the
local .NET host. Override that fallback with `PRIVATE_SEARCH_SMARTIMAGE_DOTNET`
and `PRIVATE_SEARCH_SMARTIMAGE_DLL`. TmpFiles is the default upload service;
it is temporary hosting and removes uploads after 60 minutes. You can choose
`Litterbox`, `Pomf`, or `Catbox` with
`PRIVATE_SEARCH_SMARTIMAGE_UPLOAD_ENGINE` if your network permits that service.

Reverse-image search uploads the selected local image to SmartImage's enabled
search engines, so Theia asks for confirmation before it runs. Results are
untrusted matches, not proof of identity, ownership, or authorship.

InsightFace runs locally in its own worker process before SmartImage runs. It
indexes supported files under the project `image/` folder, stores embeddings in
`var/face-index.sqlite` by default, and writes aligned crops under
`var/face-crops/`. Override the worker interpreter, roots, timeout, model,
provider policy, image root, index path, crop path, and crop-retention behavior
with `PRIVATE_SEARCH_INSIGHTFACE_*`.

The combined reverse-image workflow is not fully offline. Face detection,
embedding, and local index search stay on the local machine, but SmartImage and
Blackbird are networked and remain confirmation-gated. Theia keeps one privacy
checkpoint before any SmartImage upload, and the resulting local plus web
matches are filtered to a 75% minimum confidence threshold before being shown.

When you add or remove files under `image/`, the local face index is refreshed
the next time InsightFace runs. The query image itself must stay inside that
folder so the worker cannot be pointed at arbitrary paths outside the project.

These paths are ignored by Git. Do not commit downloaded media, cookies,
credentials, or cache databases.

## Development

Run the local quality checks before submitting a change:

```bash
ruff check .
pytest -q
python -m compileall -q src tests main.py benchmarks
```

The same checks run in GitHub Actions on Python 3.12, 3.13, and 3.14 for pushes
and pull requests targeting `main`. See
[`docs/architecture.md`](docs/architecture.md) for the component overview and
[`docs/spec-process-cicd-ci.md`](docs/spec-process-cicd-ci.md) for the CI
workflow specification.

## Troubleshooting

**yt-dlp reports missing FFmpeg or `ffprobe`.** Install FFmpeg and verify that
`ffmpeg -version` and `ffprobe -version` work in the same shell used to run the
application. On Windows, restart PowerShell after installing FFmpeg so the
updated `PATH` is loaded.

**A site returns HTTP 403, 404, or a bot challenge.** Site layouts and access
controls change independently of this project. The adapter reports the failure
and the remaining configured sources continue when possible.

**Blackbird does not start or reports a missing worker interpreter.** Run
`.\scripts\setup_blackbird.ps1`, or point `PRIVATE_SEARCH_BLACKBIRD_PYTHON` at
the isolated interpreter under `Update/blackbird/.venv/Scripts/python.exe`.

**Blackbird results look stale.** The packaged worker keeps site-list updates
disabled by default. Set `PRIVATE_SEARCH_BLACKBIRD_UPDATE_SITES=1` only for an
intentional refresh run, then restore it to `0`.

**InsightFace reports CPU degraded mode or no CUDA provider.** Rerun
`.\scripts\setup_insightface.ps1` and check the provider output. The worker
expects `onnxruntime-gpu==1.27.0`, a compatible NVIDIA driver, and matching CUDA
or cuDNN runtime libraries on `PATH`. CPU fallback is allowed only when
`PRIVATE_SEARCH_INSIGHTFACE_PROVIDER_POLICY=cpu` or `cuda_or_cpu`.

**InsightFace asks for missing model files.** The setup script does not download
weights. Manually place the licensed model pack under
`~/.insightface/models/<model_name>/`, or run the documented explicit download
command yourself if you accept the network transfer and the model license terms.

**Reverse-image search misses newly added local photos.** Put supported files
under the project `image/` folder and rerun the reverse-image workflow. The
worker refreshes the local SQLite face index during that run.

**Worker errors mention paths, timeouts, or unsupported images.** Confirm the
`PRIVATE_SEARCH_BLACKBIRD_*` and `PRIVATE_SEARCH_INSIGHTFACE_*` variables point
to existing files inside the expected roots. InsightFace only accepts supported
image files that live under the configured image root.

**Lustpress results are unavailable.** Confirm `LUSTPRESS_BASE_URL` is correct
and that the service is reachable before starting the search interface.

## Responsible use

Use this software only where you have the legal right and permission to access
and download the content. Respect applicable law, site terms, copyright, age
requirements, rate limits, and creator rights.
