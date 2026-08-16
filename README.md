# Qt-Downloader

Qt-Downloader is a local terminal application for searching configured video
sites, inspecting candidate links with [yt-dlp](https://github.com/yt-dlp/yt-dlp),
deduplicating results by title and available quality, and downloading a selected
video. Runtime data stays on the local machine.

## Features

- Concurrent searches across the configured site adapters.
- Include filtering and default exclusion of `ai`, `ai-generated`, and `vr`.
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

## Usage

After installing (`python -m pip install -e ".[dev]"`), the `qt` command is
available:

```bash
qt search "video title" --filter hd --exclude vr --min-views 1000
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

`main.bat` is the supported Windows launcher; it opens the interactive menu
with the project virtual environment automatically, so activation is not
required.

Downloads are saved under `var/downloads/`. Enter `q` and press Return when
prompted during a download to request cancellation; press `Ctrl+C` to
interrupt the application.

For sources that provide HLS or DASH fragments, downloads use four concurrent
fragments by default. Adjust this conservatively with
`PRIVATE_SEARCH_CONCURRENT_FRAGMENTS` (capped at 8). An optional
`PRIVATE_SEARCH_HTTP_CHUNK_SIZE` such as `10M` enables yt-dlp HTTP chunking;
leave it unset unless the source benefits from it.

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
rendered in a terminal table. Tookie username OSINT is wired through an
isolated subprocess, writes its JSON report in a temporary directory, and is
still confirmation-gated. The model-to-tool orchestrator keeps bounded history.

### SmartImage Rdx reverse-image search

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
and `PRIVATE_SEARCH_SMARTIMAGE_DLL`. Catbox is the default upload service;
explicitly choose `Litterbox`, `Pomf`, or `TmpFiles` with
`PRIVATE_SEARCH_SMARTIMAGE_UPLOAD_ENGINE` if your network permits that service.

Reverse-image search uploads the selected local image to SmartImage's enabled
search engines, so Theia asks for confirmation before it runs. Results are
untrusted matches, not proof of identity, ownership, or authorship.

Tookie uses `Update/tookie-osint/.venv` automatically when that environment
exists. To use a different installation, set `PRIVATE_SEARCH_TOOKIE_ROOT` and
`PRIVATE_SEARCH_TOOKIE_PYTHON`. Its scan timeout and worker count are controlled
by `PRIVATE_SEARCH_TOOKIE_TIMEOUT` and `PRIVATE_SEARCH_TOOKIE_THREADS`.

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

**Lustpress results are unavailable.** Confirm `LUSTPRESS_BASE_URL` is correct
and that the service is reachable before starting the search interface.

## Responsible use

Use this software only where you have the legal right and permission to access
and download the content. Respect applicable law, site terms, copyright, age
requirements, rate limits, and creator rights.
