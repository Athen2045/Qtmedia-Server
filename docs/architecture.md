# Architecture

The repository has one interactive menu, two scriptable console commands, and
small modules organized by responsibility.

```text
main.bat / main.py / python -m private_search
        |
        v
src/private_search/
  app/
    cli.py       interactive menu and Typer commands
  search/
    engine.py    concurrent retrieval, inspection, filters and ranking
    quality.py   tokenization and relevance scoring
    preview.py   bounded Kitty thumbnail cache and renderer
  download/
    engine.py    direct URL validation and yt-dlp downloads
    control.py   cancellation primitives
    transfer.py  shared transfer settings
  sources/
    lustpress.py / pmvhaven.py  site-specific adapters
  net/
    http_client.py              bounded HTTP transport
  config.py                     stable runtime paths
        |
        v
var/
  downloads/     downloaded media
  cache/         SQLite inspection cache
```

`main.bat` is the normal Windows entry point. New code should import the
package modules or use the `private-search` and `private-download` console
commands. The application layer depends on search and download engines, while
site adapters and HTTP transport remain behind focused interfaces.
Site-specific scraping remains behind the `SiteAdapter` interface, allowing an
adapter to change without changing the search pipeline.

Runtime data is excluded from version control. This keeps repository locality
focused on implementation and prevents media or cache state from entering a
private GitHub repository accidentally.

The optional local AI runtime is managed by `private_search.ai.runtime`. It
defaults to the downloaded Qwen GGUF, its vision projector, and the bundled
CUDA-enabled llama.cpp server under `var/` when present. The manager passes
`--device CUDA0 --gpu-layers 999` for the first NVIDIA GPU and accepts
environment overrides from `.env.example`. It binds only to `127.0.0.1` by
default, waits for `/health`, and terminates the child process when its context
exits. Model/runtime binaries are intentionally ignored by Git.

The local chat client sends non-thinking requests to `/v1/chat/completions`.
The model can only return the validated action types defined by
`private_search.ai.actions`; it cannot create shell commands or choose an
executable path. Tool execution and confirmation prompts are separate layers
consumed by `private_search.ai.chat`. The orchestrator maintains bounded
history and returns a normalized `ChatTurnResult`; it no longer keeps mutable
"active image" session state. `private_search.app.chat_ui` is the default Rich
prompt layer. It starts and stops llama.cpp around the session, exposes only
`/about`, `/help`, and `/quit`, and keeps the existing Typer commands available
for scripted search and download workflows. A successful search renders
numbered results, then routes the selected result through a UI-created
`download_media` action so the existing confirmation gate is preserved. When a
reverse-image action needs a local file, the UI scans the project `image`
folder recursively, auto-selects the only supported candidate, or presents a
numbered picker with Kitty-optional previews before the confirmation step.
SmartImage uploads remain confirmation-gated and are never triggered by the
picker alone. The UI presents the assistant as Theia and exposes `/about` with
the active model and safeguard summary; this persona layer does not grant the
model shell, filesystem, or unrestricted tool access.

Chat searches derive their source scope from the user's original wording. The
`porn` scope selects XHamster, XVideos, YouJizz, SpankBang, TNAFlix, PMVHaven,
and YouPorn; `youtube` selects YouTube. The model action contains only the
title query, so model-generated include filters, exclusions, and view
thresholds cannot silently remove results. The legacy Typer command still
accepts its explicit one-shot search options for scripted workflows.
