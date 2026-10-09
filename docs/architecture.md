# Architecture

The workspace contains a standalone CLI and a separate desktop application.
They use separate entry points, tests, runtime directories, and packaging
metadata.

```text
Qtmedia/
├── src/qtmedia/
│   ├── app/       CLI menu and Typer commands
│   ├── search/    retrieval, ranking, cache, and preview
│   ├── download/  direct URL validation, transfer, and cancellation
│   ├── sources/   CLI source adapters
│   ├── net/       bounded HTTP transport
│   └── config.py  CLI runtime paths
├── tests/
├── benchmarks/
└── var/
    ├── downloads/  CLI downloaded media
    └── cache/      CLI search cache

QtmediaApp/
├── frontend/      Tauri/React desktop interface
├── src-tauri/     Rust host and sidecar bridge
└── sidecar/       packaged Python CLI engine
```

The desktop application consumes the CLI engine through its sidecar boundary;
there is no network server between them. The CLI remains independently usable,
and its runtime data is not shared with the desktop UI.

The CLI uses `main.py`, `main.bat`, `qt`, `qtmedia-search`, and
`qtmedia-download`. The desktop application keeps its frontend, Rust host,
and sidecar build artifacts under `QtmediaApp/`.

Runtime data is excluded from version control. Application-specific guidance
and current state live in `Qtmedia/` and `QtmediaApp/` alongside the code they
govern.
