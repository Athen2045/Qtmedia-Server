# Architecture

The workspace contains two independent Python applications. They use separate
packages, entry points, tests, runtime directories, and packaging metadata.

```text
Qtmedia/
├── src/qtmedia/
│   ├── app/       CLI menu and Typer commands
│   ├── search/    retrieval, ranking, cache, and preview
│   ├── download/  direct URL validation, transfer, and cancellation
│   ├── sources/   CLI source adapters
│   ├── net/       bounded HTTP transport
│   └── config.py  CLI runtime paths
├── tests/
├── benchmarks/
└── var/
    ├── downloads/  CLI downloaded media
    └── cache/      CLI search cache

QTmediaBot/
├── src/qtmedia_bot/
│   ├── bot/       Telegram application, handlers, services, and storage
│   ├── download/  bot-owned copy of transfer support
│   ├── sources/   bot-owned provider support
│   └── net/       bot-owned copy of HTTP transport
├── tests/
├── var/
│   ├── telegram_jobs/   short-lived native job media
│   └── telegram_state/  short-lived native metadata
└── deploy/telegram/
```

The copied bot support modules are intentional. The bot does not import the
CLI package, and the CLI does not import the bot package. This prevents a
change to shared-looking transfer, network, or source code from silently
changing the other application. Search, ranking, previews, and search cache
remain CLI-only.

The CLI uses `main.py`, `main.bat`, `qt`, `qtmedia-search`, and
`qtmedia-download`. The bot uses the `qtmedia-bot` entry point and the Docker
Compose files under `QTmediaBot/deploy/telegram/`.

The Telegram deployment runs the bot and a pinned Local Bot API image on a
private network with no published API port. Both services mount the same named
`telegram_jobs` volume at `/var/lib/qtmedia/telegram_jobs`. The delivery
transport passes a validated local path to the Local Bot API, classifies
ambiguous upload results without retrying, and removes temporary job data
through the documented cleanup lifecycle.

The Telegram application accepts direct media links only. Its inspection,
quality selection, admission limits, callback ownership, privacy boundaries,
and cleanup rules are defined in
[`superpowers/specs/telegram-setup.md`](superpowers/specs/telegram-setup.md).
The benchmark procedure is in
[`benchmarks/telegram-milestone-6.md`](benchmarks/telegram-milestone-6.md).

Runtime data is excluded from version control. Application-specific guidance
and current state live in `Qtmedia/` and `QTmediaBot/` alongside the code they
govern.
