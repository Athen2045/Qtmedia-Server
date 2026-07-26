# Private Search

Private Search is a local terminal application for searching configured video
sites, inspecting candidate URLs with [yt-dlp](https://github.com/yt-dlp/yt-dlp),
deduplicating results by title and quality, and downloading selected videos.

## Run

Create or activate the project virtual environment, then run either command:

```bash
./.venv/bin/python private.py       # search interface
./.venv/bin/python main.py          # direct-link downloader
```

The package entry point is also available after an editable install:

```bash
python -m pip install -e .
python -m private_search
python -m private_search.downloader
```

FFmpeg is required when yt-dlp must merge separate audio and video streams.
On macOS: `brew install ffmpeg`.

## Project layout

```text
src/private_search/   Application modules
tests/                Automated tests
scripts/              Developer helpers
var/downloads/        Downloaded media (ignored by Git)
var/cache/            SQLite inspection cache (ignored by Git)
```

Runtime data is deliberately outside the source package. Do not commit media,
cookies, credentials, or cache databases to a repository.
