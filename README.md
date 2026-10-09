# Qtmedia Workspace

Qtmedia is a media-download workspace with a standalone CLI and a desktop
application:

- [Qtmedia CLI](Qtmedia/README.md) is a local terminal tool for searching
  configured media sources, inspecting available formats, and downloading a
  selected result.
- [QtmediaApp](QtmediaApp/README.md) is the desktop application built around
  the CLI engine through a local sidecar boundary.

## Technology

The CLI uses Python 3.11+, yt-dlp, FFmpeg, Requests, pytest, Typer, Rich,
Beautiful Soup, RapidFuzz, and optional browser-impersonation support. The
desktop application uses Tauri, React/TypeScript, and the packaged CLI engine.

## Repository layout

```text
Qtmedia/       Standalone CLI project, tests, docs, benchmarks, and runtime data
QtmediaApp/    Desktop application project and sidecar integration
docs/          Architecture, research, plans, and runbooks
```

See the [folder structure blueprint](docs/Project_Folders_Structure_Blueprint.md)
for placement and naming conventions.

## Getting started

Choose the application you want to run and follow its local README. The CLI
can be installed from `Qtmedia/` with an editable Python install. Follow
`QtmediaApp/setup.md` for desktop development.

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
`Qtmedia/` or `QtmediaApp/` before making a change. Keep changes within the
owning application unless a root documentation or CI reference must also be
updated.

Before opening a pull request, run the focused checks from the application
directory:

```bash
ruff check .
pytest -q
python -m compileall -q src tests
```

For CLI changes, also compile `main.py` and `benchmarks`. For desktop changes,
run the frontend, sidecar, and packaging checks described in `QtmediaApp/setup.md`.

Use clear commit messages, explain behavior changes, and include tests for
new or changed functionality. Contributions must preserve the documented
privacy, source-validation, rate-limit, size-limit, callback-ownership, and
cleanup requirements.

## Responsible use

Use the software only with content and services you are authorized to access
and download. Respect applicable law, service terms, copyright, privacy,
security, rate limits, and creator rights.
