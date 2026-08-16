import io
import sys
import threading
import time

import pytest

from private_search.download import control as download_control
from private_search.download.control import (
    DownloadCancellation,
    DownloadCancelled,
)


class _FakeStdin(io.StringIO):
    """A stdin stand-in whose tty-ness the test controls."""

    def __init__(self, text: str = "", tty: bool = True) -> None:
        super().__init__(text)
        self._tty = tty
        self.reads = 0

    def isatty(self) -> bool:
        return self._tty

    def readline(self, *args, **kwargs) -> str:
        self.reads += 1
        return super().readline(*args, **kwargs)

    def fileno(self) -> int:
        # select() needs a real descriptor; stdin of the test process is a
        # pipe that never becomes readable, which is what we want here.
        return sys.__stdin__.fileno() if sys.__stdin__ else 0


def test_progress_hook_raises_once_cancelled():
    cancellation = DownloadCancellation()
    cancellation.progress_hook({})  # not cancelled: no-op
    cancellation.cancelled.set()
    with pytest.raises(DownloadCancelled):
        cancellation.progress_hook({})


def test_listener_does_not_start_when_stdin_is_not_a_tty(monkeypatch, capsys):
    """Piped stdin belongs to the caller; the listener must not consume it."""
    piped = _FakeStdin("https://example.com/videos/next-url\n", tty=False)
    monkeypatch.setattr(sys, "stdin", piped)

    cancellation = DownloadCancellation()
    cancellation.start()
    cancellation.stop()

    assert piped.reads == 0
    assert piped.readline() == "https://example.com/videos/next-url\n"
    assert "Type 'q'" not in capsys.readouterr().out


def test_listener_does_not_start_when_stdin_is_closed(monkeypatch):
    closed = _FakeStdin("", tty=True)
    closed.close()
    monkeypatch.setattr(sys, "stdin", closed)

    cancellation = DownloadCancellation()
    cancellation.start()
    cancellation.stop()

    assert not cancellation.cancelled.is_set()


def test_stop_joins_the_listener_before_returning(monkeypatch):
    """After stop(), no thread is left reading stdin for the next prompt."""
    monkeypatch.setattr(sys, "stdin", _FakeStdin("", tty=True))
    before = {thread.name for thread in threading.enumerate()}

    cancellation = DownloadCancellation()
    cancellation.start()
    started = time.monotonic()
    cancellation.stop()
    elapsed = time.monotonic() - started

    assert elapsed < 2.0
    listeners = [
        thread
        for thread in threading.enumerate()
        if thread.name == "download-cancellation-listener" and thread.name not in before
    ]
    assert listeners == []


def test_stop_is_safe_without_start():
    cancellation = DownloadCancellation()
    cancellation.stop()
    assert not cancellation.cancelled.is_set()


def test_windows_listener_uses_console_input(monkeypatch):
    """Windows consoles cannot be passed to select.select."""
    characters = iter(["q", "\r"])
    fake_msvcrt = type(
        "FakeMsvcrt",
        (),
        {
            "kbhit": staticmethod(lambda: True),
            "getwch": staticmethod(lambda: next(characters)),
        },
    )
    monkeypatch.setattr(download_control.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

    cancellation = DownloadCancellation()
    cancellation._listen()

    assert cancellation.cancelled.is_set()
