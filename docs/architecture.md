# THEIA Architecture

THEIA has one interactive AI chat shell, two scriptable console commands, and
small modules organized by responsibility.

```text
theia / main.bat / main.py / python -m private_search
        |
        v
src/private_search/
  app/
    cli.py       scriptable Typer search/download commands
    chat_ui.py   Rich chatbot prompt and local commands
  osint/
    blackbird.py          isolated username/email worker adapter
    blackbird_worker.py   bundled JSON worker entry point
    insightface.py        local face-analysis adapter and SmartImage merge
    insightface_worker.py JSON worker entry point for local embeddings/indexing
    smartimage.py         confirmation-gated published Rdx runner
    face_store.py         persistent SQLite embedding index
  search/
    engine.py    scoped concurrent retrieval, inspection and ranking
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
  ai/
    runtime.py                  loopback llama.cpp process lifecycle
    client.py                   OpenAI-compatible local chat client
    actions.py                  strict model action schema and validator
    chat.py                     bounded model-to-tool orchestration
    confirmation.py             Rich confirmation requests and decisions
    tools.py                    confirmation-gated tool registry
  config.py                     stable runtime paths
        |
        v
var/
  downloads/     downloaded media
  cache/         SQLite inspection cache
  face-index.sqlite  local InsightFace embedding index
  face-crops/    temporary or retained aligned face crops
  models/        local model and vision-projector artifacts
  runtime/       local llama.cpp binaries
```

`theia` is the public console entry point and `main.bat` is the normal Windows
launcher. `theia-cli` exposes the scriptable search/download commands; `qt`,
`private-search`, and `private-download` remain compatibility callbacks. New
code should import the package modules or use those documented entry points.
The application layer depends on search and download engines, while
site adapters and HTTP transport remain behind focused interfaces.
Site-specific scraping remains behind the `SiteAdapter` interface, allowing an
adapter to change without changing the search pipeline.

Runtime data is excluded from version control. This keeps repository locality
focused on implementation and prevents media or cache state from entering a
private GitHub repository accidentally.

Blackbird and InsightFace are intentionally separate worker seams. The main
application chooses the action, validates inputs, and keeps the confirmation
policy, but the heavy or high-risk dependencies live in isolated worker Python
environments under `var/tools/blackbird/.venv` and `var/tools/insightface/.venv`.
That keeps the main application venv free of the OSINT worker dependency stacks
and reduces the chance of launching those workers with the wrong interpreter.

The optional local AI runtime is managed by `private_search.ai.runtime`. It
defaults to the downloaded Qwen GGUF, its vision projector, and the bundled
CUDA-enabled llama.cpp server under `var/` when present. The manager passes
`--device CUDA0 --gpu-layers 999` for the first NVIDIA GPU and accepts
environment overrides from `.env.example`. It binds only to `127.0.0.1` by
default, waits for `/health`, and terminates the child process when its context
exits. Model/runtime binaries are intentionally ignored by Git.

The local chat client sends requests to `/v1/chat/completions`.
The first pass classifies the request against the validated action types defined
by `private_search.ai.actions`. Ordinary conversation, coding, debugging,
planning, and analysis then use a separate free-form response pass with
thinking enabled; its reasoning field is discarded and hidden chain-of-thought
is never shown. The model cannot execute shell commands or choose an executable
path. Tool execution and confirmation prompts are separate layers consumed by
`private_search.ai.chat`. The orchestrator maintains bounded history and returns a normalized `ChatTurnResult`; it no longer keeps mutable
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

Reverse-image search is a composite flow rather than one opaque tool call. The
chat UI selects a local file from `var/images/`, InsightFace runs
local face detection and embedding generation in the isolated worker, the
worker refreshes and queries the local SQLite face index, and only then does
the confirmed SmartImage adapter run web reverse-image searches for the
original image and any aligned face crops. The merged result set is filtered by
confidence before presentation.

Confirmed external operations use a shared streaming progress seam. Workers
keep one final JSON response on stdout and write lines prefixed with
`THEIA_PROGRESS ` to stderr. Each event carries a phase and message and may
carry an exact completed/total count. The parent drains stdout and stderr
concurrently, forwards valid events to the Rich UI, and preserves ordinary
stderr as failure diagnostics. Blackbird reports one event per completed site;
InsightFace and SmartImage report staged local/upload/parse phases where an
exact remote percentage is not available.

This means the feature is not fully offline. Face embeddings, crop generation,
and local index refresh/search happen on the local machine, but SmartImage and
Blackbird are networked lookups and remain confirmation-gated. Architecture and
docs should describe that distinction explicitly so the privacy boundary stays
clear.

Chat searches derive their source scope from the user's original wording. The
`porn` scope selects XHamster, XVideos, YouJizz, SpankBang, TNAFlix, PMVHaven,
and YouPorn; `youtube` selects YouTube. The model action contains only the
title query, so model-generated include filters, exclusions, and view
thresholds cannot silently remove results. The legacy Typer command still
accepts its explicit one-shot search options for scripted workflows.
