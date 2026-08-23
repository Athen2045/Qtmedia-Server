"""Telegram media delivery policy behind one transport seam."""

# Small protocol and adapter classes intentionally expose one deep operation.
# pylint: disable=too-few-public-methods

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from telegram import InputFile
from telegram.error import NetworkError, TelegramError, TimedOut
from telegram.request import HTTPXRequest

VIDEO_SUFFIXES = frozenset({".avi", ".flv", ".mkv", ".mov", ".mp4", ".ts", ".webm"})
VIDEO_DOCUMENT_THRESHOLD_BYTES = 1_000_000_000


class DeliveryError(RuntimeError):
    """A stable Telegram delivery outcome safe for lifecycle handling."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class DeliverableMedia:
    """A validated local file ready for Telegram delivery."""

    path: Path
    media_type: str


class DeliveryTransport(Protocol):
    """The single delivery operation used by the job lifecycle."""

    async def deliver(self, message, media: DeliverableMedia) -> None:
        """Deliver media or raise a stable :class:`DeliveryError`."""


class _UploadAdapter(Protocol):
    @contextmanager
    def prepare(self, path: Path) -> Iterator[Path | InputFile]:
        """Yield the Telegram input representation and own its lifetime."""


class _LocalPathAdapter:
    @contextmanager
    def prepare(self, path: Path) -> Iterator[Path]:
        """Yield a shared path without opening the media in Python."""
        yield path


class _MultipartAdapter:
    @contextmanager
    def prepare(self, path: Path) -> Iterator[InputFile]:
        """Yield a streaming input and close its owned handle afterward."""
        with path.open("rb") as file_handle:
            yield InputFile(
                file_handle,
                filename=path.name,
                read_file_handle=False,
            )


class TelegramDeliveryTransport:
    """Own Telegram request settings, upload resources, and outcomes."""

    def __init__(self, *, local_mode: bool, timeout_seconds: float):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = timeout_seconds
        self._adapter: _UploadAdapter = (
            _LocalPathAdapter() if local_mode else _MultipartAdapter()
        )
        self.request = HTTPXRequest(
            read_timeout=timeout_seconds,
            write_timeout=timeout_seconds,
            connect_timeout=min(30, timeout_seconds),
            pool_timeout=min(30, timeout_seconds),
            media_write_timeout=timeout_seconds,
        )

    async def deliver(self, message, media: DeliverableMedia) -> None:
        """Deliver once, classifying ambiguous outcomes without retrying."""

        try:
            await asyncio.wait_for(
                self._send(message, media),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as error:
            raise DeliveryError("upload_unconfirmed") from error
        except (TimedOut, NetworkError) as error:
            raise DeliveryError("upload_unconfirmed") from error
        except (OSError, TelegramError) as error:
            raise DeliveryError("upload_failed") from error

    async def _send(self, message, media: DeliverableMedia) -> None:
        with self._adapter.prepare(media.path) as input_file:
            if media.media_type == "audio":
                await message.reply_audio(audio=input_file)
            elif media.path.suffix.casefold() in VIDEO_SUFFIXES:
                if media.path.stat().st_size <= VIDEO_DOCUMENT_THRESHOLD_BYTES:
                    await message.reply_video(
                        video=input_file,
                        supports_streaming=True,
                    )
                else:
                    await message.reply_document(document=input_file)
            else:
                await message.reply_document(document=input_file)
