# Qt-Downloader

Qt-Downloader is a local graphical application for searching configured video
sites, inspecting candidate links with [yt-dlp](https://github.com/yt-dlp/yt-dlp),
deduplicating results by title and available quality, and downloading a selected
video. Runtime data stays on the local machine.

## Features

- Concurrent searches across the configured site adapters.
- Include filtering and default exclusion of `ai`, `ai-generated`, and `vr`.
- URL and title deduplication before and after yt-dlp inspection.
- Persistent SQLite inspection cache to avoid reprocessing known URLs.
- Progressive result display and interactive download selection.
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

## Installation

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Usage

Start the search interface:

```bash
python search.py
```

Start the direct-link downloader:

```bash
python download.py
```

The installed console commands are also available:

```bash
private-search
private-download
```

The search interface prompts for a title, applies the configured filters, and
shows matching preview links. The downloader prompts for a URL and saves the
result under `var/downloads/`. Enter `q` and press Return when prompted during a
download to request cancellation; press `Ctrl+C` to interrupt the application.

## Optional Lustpress integration

Point the search interface at a local Lustpress REST service before starting it:

```bash
export LUSTPRESS_BASE_URL=http://localhost:3000
python search.py
```

Lustpress can supplement the built-in adapters for supported sites. It does not
replace yt-dlp or the direct-link downloader. The service must be configured and
running separately.

## Runtime data and configuration

- `var/cache/search.sqlite3` stores inspection results.
- `var/downloads/` stores downloaded media.
- `.env.example` documents optional environment settings.

These paths are ignored by Git. Do not commit downloaded media, cookies,
credentials, or cache databases.

## Development

Run the local quality checks before submitting a change:

```bash
ruff check .
pytest -q
python -m compileall -q src tests search.py download.py
```

The same checks run in GitHub Actions on Python 3.12, 3.13, and 3.14 for pushes
and pull requests targeting `main`. See
[`docs/architecture.md`](docs/architecture.md) for the component overview and
[`docs/spec-process-cicd-ci.md`](docs/spec-process-cicd-ci.md) for the CI
workflow specification.

## Troubleshooting

**yt-dlp reports missing FFmpeg or `ffprobe`.** Install FFmpeg and verify that
`ffmpeg -version` and `ffprobe -version` work in the same shell used to run the
application.

**A site returns HTTP 403, 404, or a bot challenge.** Site layouts and access
controls change independently of this project. The adapter reports the failure
and the remaining configured sources continue when possible.

**Lustpress results are unavailable.** Confirm `LUSTPRESS_BASE_URL` is correct
and that the service is reachable before starting the search interface.

## Responsible use

Use this software only where you have the legal right and permission to access
and download the content. Respect applicable law, site terms, copyright, age
requirements, rate limits, and creator rights.
