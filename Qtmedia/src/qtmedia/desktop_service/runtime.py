"""JavaScript runtime selection for desktop yt-dlp calls."""

from __future__ import annotations

import os
from pathlib import Path

from ..download.transfer import javascript_runtime_options as configured_runtime_options


def javascript_runtime_options() -> dict[str, object]:
    """Prefer the Deno binary shipped with the desktop app.

    YouTube's player challenges need a JS runtime; without one, stream URLs are
    intermittently refused. Deno is yt-dlp's recommended runtime and runs the
    solver without file-system or network access. Outside the packaged app the
    CLI's configured lookup still applies.
    """
    bundled = os.getenv("QTMEDIA_DENO")
    if bundled and Path(bundled).is_file():
        return {"js_runtimes": {"deno": {"path": bundled}}}
    return configured_runtime_options()
