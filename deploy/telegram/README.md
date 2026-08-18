# Telegram deployment boundary

This directory is reserved for the Telegram runtime deployment:

- `Dockerfile` for the bot application;
- `compose.yaml` for the bot and Local Bot API services;
- deployment-only health checks and operator commands.

The deployment must follow [`telegram-setup.md`](../../docs/superpowers/specs/telegram-setup.md). Credentials belong in a local ignored `.env`, never in this directory or Git.

The deployment is not wired yet. Add files here only when the corresponding implementation milestone is approved.
