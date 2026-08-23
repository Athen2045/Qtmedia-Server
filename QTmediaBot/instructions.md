# QTmediaBot Instructions

## Scope

QTmediaBot owns direct-link Telegram handling, inspection, quality selection,
download jobs, delivery, cleanup, and the Local Bot API deployment.

## File placement

- Telegram application: `src/qtmedia_bot/bot/`
- Bot services and handlers: `src/qtmedia_bot/bot/services/` and
  `src/qtmedia_bot/bot/handlers/`
- Bot-owned transfer support: `src/qtmedia_bot/download/`
- Copied HTTP support: `src/qtmedia_bot/net/`
- Copied source support: `src/qtmedia_bot/sources/`
- Runtime job media: `var/telegram_jobs/`
- Runtime metadata: `var/telegram_state/`
- Bot tests: `tests/bot/`
- Deployment tests and files: `tests/deploy/` and `deploy/telegram/`

## Safety rules

- Keep raw URLs and sensitive media metadata out of persistent bot state and
  normal logs.
- Preserve source allowlists, HTTPS/IP validation, bounded jobs, rate limits,
  callback ownership, upload outcome classification, and cleanup guarantees.
- Do not add automatic upload retries or bypass authentication, DRM, paywalls,
  geo-restrictions, or source terms.
- Keep bot changes inside `QTmediaBot/`; the CLI has its own copied modules.

## Verification

From `QTmediaBot/`, run:

```bash
ruff check .
pytest -q
python -m compileall -q src tests
docker compose --env-file .env -f deploy/telegram/compose.yaml config --quiet
```

Use the [Telegram setup specification](../docs/superpowers/specs/telegram-setup.md)
and [Milestone 6 runbook](../docs/benchmarks/telegram-milestone-6.md) for live
acceptance work.
