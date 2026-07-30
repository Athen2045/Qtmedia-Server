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

### Optional Lustpress search backend

You can run a self-hosted [Lustpress](https://github.com/sinkaroid/lustpress)
instance and set its REST URL before starting the search CLI:

```bash
export LUSTPRESS_BASE_URL=http://localhost:3000
./.venv/bin/python private.py
```

Lustpress currently improves search for XHamster, XVideos, and YouPorn. Its
results enter the same filtering, deduplication, cache, and yt-dlp inspection
pipeline. It does not replace the downloader, and it has no effect on the
built-in SpankBang, TNAFlix, or YouJizz adapters, or on the separate PMVHaven
metadata adapter, all of which keep using their own scrapers.

## Known limitations

XVideos' own search backend intermittently returns HTTP 500 for specific
query terms (confirmed independent of headers, TLS fingerprint, or URL
variant — including their AMP mirror), rather than failing to reach it.
When this happens the XVideos adapter is skipped for that search; other
configured sites are unaffected.

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
