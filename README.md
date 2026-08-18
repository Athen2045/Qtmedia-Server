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

The project installs its Python dependencies from `pyproject.toml`.
Browser-impersonation support is optional; install it when a site rejects
ordinary HTTP clients:

```bash
python -m pip install -e ".[impersonation]"
```

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

This opens an interactive menu and uses the project virtual environment
automatically; activation is not required. The menu provides search, direct
download, metadata inspection, help, and quit. Inspection shows the title,
site, view count, best quality, and canonical URL without downloading the
video.

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
leave it unset unless the source benefits from it. When `curl-cffi` is
installed, `PRIVATE_SEARCH_IMPERSONATE` selects the browser profile used for
site requests; it defaults to `chrome131`.

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

In Windows PowerShell, use:

```powershell
$env:LUSTPRESS_BASE_URL = "http://localhost:3000"
private-search
```

Lustpress can supplement the built-in adapters for supported sites. It does not
replace yt-dlp or the direct-link downloader. The service must be configured and
running separately.

## Runtime data and configuration

- `var/cache/search.sqlite3` stores inspection results.
- `var/downloads/` stores downloaded media.
- `.env.example` lists optional environment settings. The application does
  not load `.env` files automatically; set variables in the shell before
  starting the command.

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
