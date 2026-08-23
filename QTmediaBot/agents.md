# QTmediaBot Agent Guide

This folder contains the Telegram bot and its independent copied runtime
modules. It does not import the Qtmedia package.

Before editing:

1. Read `context.md` and `instructions.md`.
2. Inspect `git status --short` from the workspace root.
3. Read the relevant application documentation under `docs/`, then the
   relevant sections of `../docs/superpowers/specs/telegram-setup.md`.
4. Preserve privacy, deletion, SSRF, rate-limit, size-limit, and callback
   ownership requirements.
5. Run focused bot tests and deployment checks before completion.

Do not replace bot modules with imports from `Qtmedia`. The copied modules are
an intentional change boundary.
