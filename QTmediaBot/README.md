# QTmediaBot

QTmediaBot is the standalone Telegram application in this workspace. It
accepts approved direct media links, inspects the source for available
qualities, downloads the selected media, delivers it to the requesting chat,
and removes temporary local media according to the configured lifecycle.

The bot is intentionally separate from the Qtmedia CLI. Its package contains
its own copies of the transfer, network, and provider-support modules, so bot
changes do not alter the CLI implementation. Search and search-result caching
belong exclusively to the CLI and are not part of this application.

Bot runtime data is limited to `var/telegram_jobs/` for short-lived job media
and `var/telegram_state/` for short-lived operational metadata.

## Setup

The supported laptop deployment uses Docker Desktop with WSL2 and a private
Local Bot API service. Follow the [Telegram setup specification](../docs/superpowers/specs/telegram-setup.md)
and the [deployment runbook](deploy/telegram/README.md) before starting the
stack. Keep credentials in the ignored `.env` file and never commit them.

## Development

Run these commands from the `QTmediaBot` directory:

```bash
python -m pip install -e ".[dev]"
ruff check .
pytest -q
python -m compileall -q src tests
```

Build and operate the Docker deployment with the commands in
[`deploy/telegram/README.md`](deploy/telegram/README.md). The bot uses Python,
`python-telegram-bot`, yt-dlp, FFmpeg, Docker Compose, and a pinned Local Bot
API build.

Read [`instructions.md`](instructions.md) before changing privacy, storage,
source validation, upload, or cleanup behavior. Application-specific
documentation is indexed in [`docs/`](docs/).
