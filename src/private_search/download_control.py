"""Interactive cancellation support for yt-dlp downloads."""

from __future__ import annotations

import sys
import threading


class DownloadCancelled(Exception):
    """Raised by a yt-dlp progress hook when the user requests cancellation."""


class DownloadCancellation:
    """Listen for ``q`` + Enter while yt-dlp is downloading."""

    def __init__(self) -> None:
        self.cancelled = threading.Event()
        self._stopped = threading.Event()
        self._listener = threading.Thread(
            target=self._listen,
            name="download-cancellation-listener",
            daemon=True,
        )

    def start(self) -> None:
        print("Download started. Type 'q' and press Enter to cancel.")
        self._listener.start()

    def stop(self) -> None:
        self._stopped.set()

    def progress_hook(self, _status: dict) -> None:
        if self.cancelled.is_set():
            raise DownloadCancelled

    def _listen(self) -> None:
        while not self._stopped.is_set():
            try:
                line = sys.stdin.readline()
            except (EOFError, OSError):
                return
            if not line:
                return
            if line.strip().casefold() in {"q", "quit", "exit"}:
                self.cancelled.set()
                return
