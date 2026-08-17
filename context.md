# THEIA Branch Context

This file is the handoff summary for the `Theia` branch. It records the
current source layout, the completed cleanup, and the documentation kept in
the branch so a later contributor can understand the repository without
reconstructing the earlier task history.

## Branch state

- Branch: `Theia`
- Public project name: `THEIA`
- Internal Python import namespace: `private_search` for compatibility.
- The branch contains the current working-tree changes from the codebase
  inspection and cleanup. They still need to be reviewed, committed, and
  pushed as a branch before any pull request is opened.
- `main` was not rewritten or merged.

## What has been completed

### Code and architecture

- Removed the obsolete interactive menu and dead search helpers.
- Removed unused imports and parameters discovered during the review.
- Reused packed face embeddings during face-index writes instead of packing the
  same vector repeatedly.
- Added typed download progress and cancellation callbacks. Every yt-dlp
  transfer keeps the cancellation hook attached.
- Kept the public entry points small and explicit: `theia` for the interactive
  shell, `theia-cli` for scripted commands, and compatibility callbacks for
  `qt`, `private-search`, and `private-download`.
- Moved the THEIA Blackbird JSON worker into
  `src/private_search/osint/blackbird_worker.py`. The worker now receives the
  optional vendor root through `PRIVATE_SEARCH_BLACKBIRD_ROOT`; vendor tools
  are no longer part of the application module seam.
- Moved optional Blackbird and InsightFace runtime roots to ignored
  `var/tools/` paths. Local reverse-image inputs now default to ignored
  `var/images/`.
- Removed tests that inspected ignored SmartImage source files rather than
  testing a THEIA interface.

### Repository hygiene

- `Update/` is ignored because it is a local tool/reference drop.
- `image/` is ignored because it contains local user images. New inputs belong
  in `var/images/`, which is also ignored with the rest of `var/`.
- Historical task reports, completed SDD reports, and superseded planning or
  design files were removed. Current architecture and research references
  remain under `docs/`.
- The CI workflow now checks only the maintained `src`, `tests`, `main.py`,
  and `benchmarks` paths; stale deleted root scripts are not referenced.

## Current project structure

```text
THEIA/
├── main.py                         Windows/source-checkout launcher
├── main.bat                        Windows launcher
├── pyproject.toml                  package metadata and callbacks
├── src/private_search/             application modules
│   ├── app/                        interactive and scriptable entry points
│   ├── ai/                         local model and confirmation tools
│   ├── download/                   yt-dlp transfer modules
│   ├── net/                        bounded HTTP transport
│   ├── osint/                      worker adapters and local face index
│   ├── search/                     retrieval, ranking, and preview
│   └── sources/                    site-specific adapters
├── tests/                          unit and seam tests
├── scripts/                        optional worker setup scripts
├── docs/                           architecture, CI, and research references
├── context.md                      this branch handoff
├── Update/                         ignored local tool/reference material
├── image/                          ignored legacy local input folder
└── var/                            ignored runtime state and tool installs
```

The external-tool seam is deliberately shallow at the application surface:
THEIA validates the request and starts a worker, while the isolated vendor
implementation remains behind the configured root. The bundled Blackbird
worker is the adapter that translates the vendor result into THEIA's JSON and
progress protocol.

## Validation already performed

- `pytest -q`: 256 tests passed after the path relocation and reference-only
  SmartImage test cleanup.
- Ruff passed for `src`, `tests`, `main.py`, and `benchmarks`.
- Python compilation passed for the same maintained source paths.
- Editable installation succeeded and generated the `theia`, `theia-cli`,
  `qt`, `private-search`, and `private-download` callbacks.
- CLI help smoke tests passed for all four scriptable/compatibility callbacks.

## Markdown catalog

This catalog covers the Markdown files kept in the project source tree. The
ignored `Update/` and `var/` trees may contain vendor or runtime Markdown, but
those files are intentionally not part of THEIA's project documentation.

| File | Description |
| --- | --- |
| `context.md` | Branch handoff, cleanup summary, current structure, validation status, and this Markdown catalog. |
| `README.md` | User-facing THEIA overview, installation, entry points, optional OSINT setup, reverse-image workflow, development checks, and troubleshooting. |
| `docs/architecture.md` | Current module map, runtime seams, worker isolation, local AI lifecycle, confirmation policy, and progress protocol. |
| `docs/spec-process-cicd-ci.md` | Implementation-agnostic specification for the CI quality gate, including triggers, jobs, requirements, and validation criteria. |
| `docs/research/2026-08-16-ai-chatbot-architecture-audit.md` | Read-only audit of the local AI chatbot, OSINT integrations, model/runtime assets, and architectural risks. |
| `docs/research/2026-08-16-ai-osint-integration.md` | Research on local model, reverse-image, Blackbird, and InsightFace integration choices and constraints. |
| `docs/research/2026-08-16-blackbird-insightface-implementation-research.md` | Implementation research for isolated Blackbird and InsightFace workers, safety checks, and dependency boundaries. |
| `docs/research/2026-08-16-cuda-theia-model-audit.md` | Hardware, CUDA, llama.cpp, GGUF, and model-projector audit for the local THEIA runtime. |
| `docs/research/2026-08-16-performance-search-cli.md` | Performance and UX research covering HTTP retrieval, search concurrency, ranking, downloads, and CLI behavior. |
| `docs/research/2026-08-16-smartimage-python-rewrite-face-recognition-feasibility.md` | Feasibility analysis for replacing SmartImage or combining it with local face recognition. |
| `docs/research/2026-08-16-theia-personality-safeguard-audit.md` | Audit of THEIA's assistant persona, tool restrictions, confirmation gates, and safeguard messaging. |
| `docs/research/2026-08-16-yt-dlp-thumbnails-metadata.md` | Research on yt-dlp metadata, thumbnails, format selection, and the download/search integration. |
| `docs/research/2026-08-17-codebase-optimization.md` | Record of the dead-code removal, callback cleanup, face-index optimization, and verification from the codebase review. |
| `docs/research/2026-08-17-firecrawl-theia-evaluation.md` | Evaluation of Firecrawl against THEIA's search, scraping, and reverse-image requirements. |
| `docs/research/2026-08-17-theia-capability-performance-research.md` | Capability and performance review of local AI, OSINT, search, downloads, and worker execution. |

## Next handoff steps

1. Re-run the full test, lint, compile, and documentation-link checks after the
   path cleanup.
2. Review the final diff and verify that ignored `Update/`, `image/`, and
   `var/` content is not staged.
3. Commit the branch and push it with `git push -u origin Theia`.
