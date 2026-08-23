# Qtmedia CLI

Qtmedia is the standalone command-line application in this workspace. It
searches configured media sources, inspects candidate links with yt-dlp, and
downloads a selected result to the local machine.

## Requirements

- Python 3.11 or newer
- FFmpeg and `ffprobe` on `PATH`
- Network access to the configured sources

## Install

Run these commands from the `Qtmedia` directory:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

On Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Install optional browser impersonation support with
`python -m pip install -e ".[impersonation]"` when a permitted source requires
it.

## Use

```bash
qt search "title"
qt download https://example.com/media
```

The `qtmedia-search` and `qtmedia-download` console aliases remain available
for scripts. On Windows, `main.bat` starts the interactive menu using the
project virtual environment.

Runtime data is kept under `var/downloads/` and `var/cache/` only. Do not
commit downloaded media, cookies, credentials, or cache databases.

## Development

From this directory:

```bash
ruff check .
pytest -q
python -m compileall -q src tests main.py benchmarks
```

See [`../docs/architecture.md`](../docs/architecture.md) for the workspace
architecture and [`instructions.md`](instructions.md) for the CLI contribution
workflow. Application-specific documentation is indexed in [`docs/`](docs/).
