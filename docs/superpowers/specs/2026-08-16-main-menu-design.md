# Unified Interactive Launcher Design

## Goal

Provide one Windows-first entry point, `main.bat`, that starts a simple interactive terminal menu without requiring the user to activate the virtual environment manually.

## Menu

```text
QT Downloader

  1. Search for a video
  2. Download a video link
  3. Inspect a video link
  4. Help
  Q. Quit
```

The menu loops until the user chooses `Q`. Invalid choices show a short correction and return to the menu.

## Behavior

- Search asks for keywords, uses the existing default exclusions and ranking pipeline, renders the result table, and offers optional download selection.
- Download asks for a direct page URL, uses the existing Rich progress display, reports success/failure, and returns to the menu.
- Inspect validates a URL and uses yt-dlp metadata extraction without downloading. It displays title, site, view count, best quality, and canonical URL.
- Help displays the common commands and explains that option 3 is metadata-only.
- `main.bat` resolves its own directory and invokes `.venv\Scripts\python.exe main.py`. It fails with an actionable setup message if the virtual environment is absent.
- Existing `qt`, `qtmedia-search`, `qtmedia-download`, `search.py`, and `download.py` compatibility paths remain available.

## Architecture

`main.py` becomes the root launcher and delegates to `qtmedia.app.cli.interactive_menu`. The menu is a thin presentation module over the existing deep search, inspection, and download interfaces; it does not duplicate network or yt-dlp logic.

## Testing

- Test each menu choice routes to the correct operation.
- Test option 3 calls inspection and never calls download.
- Test invalid choices loop rather than exit.
- Test `main.py` adds `src` and invokes the menu.
- Keep the existing full test, lint, and compile checks green.
