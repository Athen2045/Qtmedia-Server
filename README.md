# Qtmedia Workspace

Qtmedia is a Python media-download workspace with two deliberately independent
applications:

- [Qtmedia CLI](Qtmedia/README.md) is a local terminal tool for searching
  configured media sources, inspecting available formats, and downloading a
  selected result.
- [QTmediaBot](QTmediaBot/README.md) is a privacy-conscious Telegram bot for
  approved direct media links. It presents source-available quality choices,
  delivers the selected file to the requesting chat, and cleans up temporary
  local media.

The applications do not share runtime source files. The bot contains copied
support modules under its own package so that a change to one application does
not silently change the other.

## Technology

Both applications are built with Python 3.11+, yt-dlp, FFmpeg, Requests, and
pytest. The CLI uses Typer, Rich, Beautiful Soup, RapidFuzz, and optional
browser-impersonation support. The bot uses `python-telegram-bot`, Docker
Compose, and a pinned Local Bot API deployment for its supported laptop setup.

## Repository layout

```text
Qtmedia/       Standalone CLI project, tests, docs, benchmarks, and runtime data
QTmediaBot/    Standalone Telegram bot project, docs, tests, and Docker deployment
docs/          Architecture, setup specification, research, plans, and runbooks
```

See the [folder structure blueprint](docs/Project_Folders_Structure_Blueprint.md)
for placement and naming conventions.

## Getting started

Choose the application you want to run and follow its local README. The CLI
can be installed from `Qtmedia/` with an editable Python install. The bot's
recommended deployment is Docker Desktop with WSL2; its credentials and
allowlist are configured in an ignored `.env` file.

The bot's architecture, privacy rules, deployment requirements, and acceptance
gates are defined in the [Telegram setup specification](docs/superpowers/specs/telegram-setup.md).

## Forking and cloning

1. Fork the repository on your Git hosting service.
2. Clone your fork and enter the workspace:

   ```bash
   git clone https://github.com/<your-account>/qtmedia.git
   cd qtmedia
   ```

3. Create a feature branch:

   ```bash
   git switch -c feature/short-description
   ```

4. Install and test the application you are changing from its own directory.

Do not commit credentials, cookies, downloaded media, cache databases, local
Docker state, or generated build output.

## Contributing

Read the applicable `agents.md`, `context.md`, and `instructions.md` inside
`Qtmedia/` or `QTmediaBot/` before making a change. Keep changes within the
owning application unless a root documentation or CI reference must also be
updated.

Before opening a pull request, run the focused checks from the application
directory:

```bash
ruff check .
pytest -q
python -m compileall -q src tests
```

For CLI changes, also compile `main.py` and `benchmarks`. For bot changes,
validate the Compose file with the command in `QTmediaBot/instructions.md` and
follow the privacy-safe benchmark procedure before any live acceptance test.

Use clear commit messages, explain behavior changes, and include tests for
new or changed functionality. Contributions must preserve the documented
privacy, source-validation, rate-limit, size-limit, callback-ownership, and
cleanup requirements.

## Responsible use

Use the software only with content and services you are authorized to access
and download. Respect applicable law, service terms, copyright, privacy,
security, rate limits, and creator rights.
