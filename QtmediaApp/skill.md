# QtmediaApp Skill Map

This file maps QtmediaApp work to the relevant system skills. It is project
guidance, not a replacement for the system-provided skill catalog or each
skill's `SKILL.md`. When a skill applies, read its complete `SKILL.md` before
acting and announce its use in the commentary update.

## Always at the start of a new desktop task

- `superpowers:using-superpowers` — discover and apply the required workflow.
- `superpowers:brainstorming` — required for new product behavior, UI, or
  architecture; do not implement until the design approval gate passes.

## Design and planning

- `ui-design` — use for product UI structure, states, typography, color, and
  interaction decisions; load only its relevant product/refinement module.
- `web-design-guidelines` — use when reviewing the React UI for accessibility,
  interaction, and web-interface quality.
- `anti-ui-slop` — use when refining the visual result to prevent generic or
  decorative UI patterns.
- `superpowers:writing-plans` — use after the approved design specification is
  reviewed and before implementation begins.

## Implementation

- `superpowers:executing-plans` — use when implementing a written plan.
- `superpowers:test-driven-development` — use for new protocol, sidecar,
  library, adapter, and UI behavior.
- `typescript-expert` — use for non-trivial React/TypeScript types and
  frontend architecture.
- `fastapi-python` — use only if an approved design adds a Python HTTP API;
  the current design intentionally uses JSON Lines instead.
- `python-performance-optimization` — use when profiling sidecar startup,
  memory, media indexing, or transfer overhead.

## Debugging, security, and verification

- `superpowers:systematic-debugging` — use for test failures, runtime bugs, or
  packaging failures.
- `codex-security:security-scan` — use for a standard security review of the
  desktop boundary, capabilities, path handling, and sidecar protocol.
- `codex-security:deep-security-scan` — use only when an exhaustive audit is
  explicitly requested.
- `superpowers:verification-before-completion` — use before claiming a
  milestone is complete.
- `superpowers:requesting-code-review` — use after a substantial milestone is
  implemented and verified.

## Release and supporting work

- `superpowers:finishing-a-development-branch` — use when the user asks to
  finish, merge, or prepare a completed development branch.
- `create-github-action-workflow-specification` or
  `github-actions-templates` — use when adding the Windows/macOS build and
  release pipeline.
- `documentation-writer` — use when writing user-facing setup, privacy, or
  release documentation beyond the short app-local files.

## Selection rule

Use the smallest set of skills that covers the request. Skills named in the
system catalog take precedence over this map, and user instructions take
precedence over both. Do not load unrelated skills merely because they are
listed here.
