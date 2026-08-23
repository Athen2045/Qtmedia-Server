# Project Structure and Application Separation Design

## Goal

Separate the terminal CLI and Telegram bot into clear, independently
changeable application folders without deleting user data or silently changing
their behavior.

## Structure

```text
Qtmedia/
  src/qtmedia/       CLI package
  tests/             CLI tests
  benchmarks/        CLI benchmarks
  main.py            CLI launcher
  main.bat           Windows CLI launcher
  pyproject.toml     CLI dependencies and entry points

QTmediaBot/
  src/qtmedia_bot/   bot package and copied support modules
  tests/             bot and deployment tests
  deploy/telegram/   Docker and Local Bot API deployment
  pyproject.toml     bot dependencies and entry point
```

The CLI package is named `qtmedia`; the bot package is named `qtmedia_bot`.
Transfer, network, and provider-support modules needed by both applications
are copied into both package trees. Search, ranking, previews, and search
cache remain CLI-only. Neither application imports the other application's
runtime package.

## Workspace documentation

Root `docs/` contains architecture, research, plans, specifications, and
benchmark runbooks. Each application contains its own `README.md`, `agents.md`,
`context.md`, and `instructions.md`. The root README is the contributor entry
point and links to both applications.

## Verification

Update imports, tests, packaging metadata, Docker paths, CI commands, and
documentation whenever an application path changes. Run each application's
test and lint checks independently, compile both source trees, and validate the
bot Compose file without printing secrets.
