# QtmediaApp Agent Operating Guide

Read `context.md` first, then this file, before working inside `QtmediaApp/`.
This file defines the desktop application's local workflow. The
repository-root `agents.md` remains authoritative for workspace-wide rules.

## Required startup sequence

1. Read `QtmediaApp/context.md`.
2. Read this `agent.md`.
3. Read `QtmediaApp/setup.md` as the single operational setup and milestone
   guide.
4. Read `QtmediaApp/skill.md` and load the relevant system `SKILL.md` files
   before taking task actions.
5. Read the approved desktop design specification:
   `docs/superpowers/specs/2026-08-26-qtmedia-desktop-design.md`.
6. Read the repository-root `agents.md` and the relevant Qtmedia CLI guidance
   before changing shared behavior.
7. Inspect the working tree with `git status --short` and inspect only files
   relevant to the request.
8. State the current phase, intended change, and completion check before
   editing.

## Working rules

- `QtmediaApp/` owns the Tauri host, React UI, desktop protocol, and packaged
  Python sidecar.
- `Qtmedia/` remains the standalone CLI. Do not merge its entry point or
  runtime data into the desktop application.
- Do not implement a new milestone until the design/specification and its
  implementation plan have passed their review gates.
- Preserve unrelated user changes. Never reset, discard, or overwrite work
  without explicit authorization.
- Use `apply_patch` for file edits. Keep generated build output out of Git.
- Keep raw URLs, cookies, tokens, private media, and source responses out of
  logs, tests, documentation, and persistent application state.
- Keep sidecar communication on the local JSON Lines pipe. Do not add a
  localhost server unless the design is explicitly revised and approved.
- The user removed the 150 MB limit and internal 140 MB gate on 2026-09-15.
  Measure release size for information; prioritize reliability and required tools.
- Run focused tests after edits and report what remains unverified.

## Context maintenance

Update `QtmediaApp/context.md` whenever the phase, design, dependency set,
file layout, test result, blocker, or next action changes. Every update must
include:

- date of verification;
- current phase;
- completed work;
- next concrete action;
- open decisions or blockers;
- changed files and verification results.

When a milestone is complete, leave the file describing the next agent's
starting point.

## Completion standard

Do not claim a desktop milestone is complete unless the requested behavior and
files exist, relevant tests and checks have run, privacy and adapter policy
requirements remain intact, release size is recorded when applicable, and
`context.md` records the resulting state.
