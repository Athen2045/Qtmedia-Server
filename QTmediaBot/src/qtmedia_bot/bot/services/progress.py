"""Transient, rate-limited Telegram status reporting for one media job."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from telegram.error import TelegramError

logger = logging.getLogger(__name__)

PREPARING_TEXT = "Preparing for upload…"
UPLOAD_PENDING_TEXT = "Uploading to Telegram…\n[··········] Waiting for confirmation…"
_BAR_WIDTH = 10

MessageEditor = Callable[[str], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class DownloadProgress:
    """A numeric yt-dlp download snapshot with no source metadata."""

    downloaded_bytes: int
    total_bytes: int | None
    estimated_total_bytes: int | None
    speed_bytes_per_second: int | None


def _format_bytes(value: int) -> str:
    """Render non-negative bytes using compact decimal units."""

    if value < 1_000:
        return f"{value} B"
    amount = float(value)
    for unit in ("KB", "MB", "GB", "TB"):
        amount /= 1_000
        if amount < 1_000 or unit == "TB":
            return f"{amount:.1f} {unit}"
    return f"{amount:.1f} TB"


def _progress_bar(ratio: float | None) -> str:
    if ratio is None:
        return "[" + "·" * _BAR_WIDTH + "]"
    completed = min(_BAR_WIDTH, max(0, int(ratio * _BAR_WIDTH)))
    return "[" + "█" * completed + "░" * (_BAR_WIDTH - completed) + "]"


def render_download_progress(label: str, progress: DownloadProgress) -> str:
    """Render only measured download quantities for a Telegram status message."""

    total = progress.total_bytes
    approximate = False
    if total is None:
        total = progress.estimated_total_bytes
        approximate = total is not None
    ratio = None
    if total is not None and total > 0:
        ratio = min(1.0, max(0.0, progress.downloaded_bytes / total))
    speed = (
        f"{_format_bytes(progress.speed_bytes_per_second)}/s"
        if progress.speed_bytes_per_second is not None
        else "speed unavailable"
    )
    if ratio is None or total is None:
        details = f"{_format_bytes(progress.downloaded_bytes)} · {speed}"
        return f"Downloading {label}\n{_progress_bar(None)}\n{details}"
    total_text = _format_bytes(total)
    if approximate:
        total_text = f"~{total_text}"
    percentage = int(ratio * 100)
    details = f"{_format_bytes(progress.downloaded_bytes)} / {total_text} · {speed}"
    return f"Downloading {label}\n{_progress_bar(ratio)} {percentage}%\n{details}"


# pylint: disable=too-many-instance-attributes
class TelegramProgressReporter:
    """Bridge worker-thread yt-dlp events to one throttled Telegram edit stream."""

    def __init__(
        self,
        edit_text: MessageEditor,
        *,
        label: str,
        update_interval_seconds: int = 10,
    ) -> None:
        self._edit_text = edit_text
        self._label = label
        self._update_interval_seconds = update_interval_seconds
        self._loop = asyncio.get_running_loop()
        self._updated = asyncio.Event()
        self._latest: DownloadProgress | None = None
        self._last_text: str | None = None
        self._last_progress_edit_at: float | None = None
        self._preparing = False
        self._stopped = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Show the initial state and start the event-loop reporter task."""

        if self._task is not None:
            return
        await self._edit(f"Downloading {self._label}…")
        self._task = asyncio.create_task(self._run())

    def publish_from_worker(self, progress: DownloadProgress) -> None:
        """Accept a snapshot from a yt-dlp worker thread without I/O there."""

        self._loop.call_soon_threadsafe(self._replace_latest, progress)

    def show_preparing_from_worker(self) -> None:
        """Request an immediate preparation status from a worker-thread hook."""

        self._loop.call_soon_threadsafe(self._request_preparing)

    async def show_preparing(self) -> None:
        """Finish download reporting and show the preparation phase immediately."""

        await self.stop()
        await self._edit(PREPARING_TEXT)

    async def show_uploading(self) -> None:
        """Show an honest indeterminate status while Local Bot API confirms delivery."""

        await self.stop()
        await self._edit(UPLOAD_PENDING_TEXT)

    async def stop(self) -> None:
        """Stop the reporter before the job cleanup boundary is reached."""

        self._stopped = True
        self._updated.set()
        if self._task is not None:
            await self._task
            self._task = None

    def _replace_latest(self, progress: DownloadProgress) -> None:
        if self._stopped or self._preparing:
            return
        self._latest = progress
        self._updated.set()

    def _request_preparing(self) -> None:
        if self._stopped:
            return
        self._preparing = True
        self._updated.set()

    async def _run(self) -> None:
        while not self._stopped:
            await self._updated.wait()
            self._updated.clear()
            if self._stopped:
                return
            if self._preparing:
                await self._edit(PREPARING_TEXT)
                continue
            if self._latest is None:
                continue
            await self._wait_for_progress_window()
            if self._stopped or self._preparing or self._latest is None:
                continue
            await self._edit(render_download_progress(self._label, self._latest))
            self._last_progress_edit_at = time.monotonic()

    async def _wait_for_progress_window(self) -> None:
        if self._last_progress_edit_at is None:
            return
        deadline = self._last_progress_edit_at + self._update_interval_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                await asyncio.wait_for(self._updated.wait(), timeout=remaining)
            except TimeoutError:
                return
            self._updated.clear()
            if self._stopped or self._preparing:
                return

    async def _edit(self, text: str) -> None:
        if text == self._last_text:
            return
        try:
            await self._edit_text(text)
        except TelegramError as error:
            logger.debug("Could not update download progress: %s", type(error).__name__)
            return
        self._last_text = text
