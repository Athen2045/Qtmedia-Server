"""Interactive cancellation support for yt-dlp downloads."""

from __future__ import annotations

import select
import sys
import threading

CANCEL_WORDS = {"q", "quit", "exit"}
# How long the listener waits on stdin before rechecking whether the download
# has finished. Short enough that ``stop`` returns promptly, long enough that
# the poll costs nothing.
POLL_SECONDS = 0.1


class DownloadCancelled(Exception):
    """Raised by a yt-dlp progress hook when the user requests cancellation."""


def _stdin_is_interactive() -> bool:
    """Whether stdin is a terminal we can safely read cancel keys from.

    When stdin is a pipe or file, there is no one to press ``q`` and every
    line belongs to the caller driving the program. Reading it there would
    consume the caller's input, so the listener stays off.
    """
    stream = sys.stdin
    if stream is None or stream.closed:
        return False
    try:
        return stream.isatty()
    except (AttributeError, OSError, ValueError):
        return False


class DownloadCancellation:
    """Listen for ``q`` + Enter while yt-dlp is downloading.

    The listener only ever reads stdin *during* a download, and ``stop`` does
    not return until it has stopped reading. Without that, a thread parked in
    a blocking read outlives the download it belongs to and competes with the
    next prompt for whatever the user types.
    """

    def __init__(self) -> None:
        self.cancelled = threading.Event()
        self._stopped = threading.Event()
        self._listener: threading.Thread | None = None

    def start(self) -> None:
        if not _stdin_is_interactive():
            return
        print("Download started. Type 'q' and press Enter to cancel.")
        self._listener = threading.Thread(
            target=self._listen,
            name="download-cancellation-listener",
            daemon=True,
        )
        self._listener.start()

    def stop(self) -> None:
        self._stopped.set()
        listener, self._listener = self._listener, None
        if listener is not None:
            # Joining is what makes the handoff safe: once stop returns, the
            # listener is guaranteed not to steal the next line of input.
            listener.join(timeout=POLL_SECONDS * 10)

    def progress_hook(self, _status: dict) -> None:
        if self.cancelled.is_set():
            raise DownloadCancelled

    def _listen(self) -> None:
        while not self._stopped.is_set():
            try:
                ready, _, _ = select.select([sys.stdin], [], [], POLL_SECONDS)
            except (OSError, ValueError):
                return
            if not ready:
                continue
            # Recheck after waiting: the download may have finished while we
            # were in select, and the pending line is then the next prompt's.
            if self._stopped.is_set():
                return
            try:
                line = sys.stdin.readline()
            except (EOFError, OSError, ValueError):
                return
            if not line:
                return
            if line.strip().casefold() in CANCEL_WORDS:
                self.cancelled.set()
                return
