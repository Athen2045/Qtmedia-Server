import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from telegram import InputFile
from telegram.error import NetworkError, TelegramError, TimedOut

from qtmedia_bot.bot.services.delivery import (
    DeliverableMedia,
    DeliveryError,
    TelegramDeliveryTransport,
)


class FakeMessage:
    def __init__(self):
        self.reply_audio = AsyncMock()
        self.reply_video = AsyncMock()
        self.reply_document = AsyncMock()


def test_local_delivery_passes_shared_path_without_opening_file(tmp_path):
    media_path = tmp_path / "media.mp4"
    media_path.write_bytes(b"video")
    message = FakeMessage()
    transport = TelegramDeliveryTransport(local_mode=True, timeout_seconds=60)

    asyncio.run(transport.deliver(message, DeliverableMedia(media_path, "video")))

    assert message.reply_video.await_args.kwargs == {
        "video": media_path,
        "supports_streaming": True,
    }


def test_video_larger_than_decimal_one_gigabyte_uses_document_delivery(tmp_path):
    media_path = tmp_path / "large-media.mp4"
    media_path.write_bytes(b"video")
    message = FakeMessage()
    transport = TelegramDeliveryTransport(local_mode=True, timeout_seconds=60)

    with patch(
        "qtmedia_bot.bot.services.delivery.Path.stat",
        return_value=SimpleNamespace(st_size=1_000_000_001),
    ):
        asyncio.run(
            transport.deliver(message, DeliverableMedia(media_path, "video"))
        )

    assert message.reply_document.await_args.kwargs == {
        "document": media_path,
    }
    message.reply_video.assert_not_awaited()


def test_video_at_decimal_one_gigabyte_uses_video_delivery(tmp_path):
    media_path = tmp_path / "one-gigabyte.mp4"
    media_path.write_bytes(b"video")
    message = FakeMessage()
    transport = TelegramDeliveryTransport(local_mode=True, timeout_seconds=60)

    with patch(
        "qtmedia_bot.bot.services.delivery.Path.stat",
        return_value=SimpleNamespace(st_size=1_000_000_000),
    ):
        asyncio.run(
            transport.deliver(message, DeliverableMedia(media_path, "video"))
        )

    assert message.reply_video.await_args.kwargs == {
        "video": media_path,
        "supports_streaming": True,
    }
    message.reply_document.assert_not_awaited()


def test_native_delivery_streams_input_file_and_closes_owned_handle(tmp_path):
    media_path = tmp_path / "media.mp4"
    media_path.write_bytes(b"video")
    message = FakeMessage()
    captured = {}

    async def receive_video(**kwargs):
        captured["input_file"] = kwargs["video"]
        assert captured["input_file"].input_file_content.closed is False

    message.reply_video.side_effect = receive_video
    transport = TelegramDeliveryTransport(local_mode=False, timeout_seconds=60)

    asyncio.run(transport.deliver(message, DeliverableMedia(media_path, "video")))

    assert isinstance(captured["input_file"], InputFile)
    assert captured["input_file"].filename == "media.mp4"
    assert captured["input_file"].input_file_content.closed is True


@pytest.mark.parametrize(
    ("filename", "media_type", "method", "argument"),
    [
        ("track.mp3", "audio", "reply_audio", "audio"),
        ("track.m4a", "audio", "reply_audio", "audio"),
        ("track.flac", "document", "reply_document", "document"),
        ("track-alac.m4a", "document", "reply_document", "document"),
        ("clip.mp4", "video", "reply_video", "video"),
        ("clip.mkv", "video", "reply_video", "video"),
        ("archive.bin", "document", "reply_document", "document"),
    ],
)
def test_delivery_selects_method_from_validated_media(
    tmp_path, filename, media_type, method, argument
):
    media_path = tmp_path / filename
    media_path.write_bytes(b"content")
    message = FakeMessage()
    transport = TelegramDeliveryTransport(local_mode=True, timeout_seconds=60)

    asyncio.run(transport.deliver(message, DeliverableMedia(media_path, media_type)))

    selected = getattr(message, method)
    assert selected.await_args.kwargs[argument] == media_path


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (TimedOut(), "upload_unconfirmed"),
        (NetworkError("connection lost"), "upload_unconfirmed"),
        (TelegramError("rejected"), "upload_failed"),
    ],
)
def test_delivery_classifies_telegram_outcomes(tmp_path, failure, code):
    media_path = tmp_path / "media.mp4"
    media_path.write_bytes(b"video")
    message = FakeMessage()
    message.reply_video.side_effect = failure
    transport = TelegramDeliveryTransport(local_mode=True, timeout_seconds=60)

    with pytest.raises(DeliveryError, match=code) as raised:
        asyncio.run(
            transport.deliver(message, DeliverableMedia(media_path, "video"))
        )

    assert raised.value.code == code


def test_delivery_enforces_its_dedicated_deadline(tmp_path):
    media_path = tmp_path / "media.mp4"
    media_path.write_bytes(b"video")
    message = FakeMessage()

    async def wait_forever(**kwargs):
        del kwargs
        await asyncio.Event().wait()

    message.reply_video.side_effect = wait_forever
    transport = TelegramDeliveryTransport(local_mode=True, timeout_seconds=0.01)

    with pytest.raises(DeliveryError, match="upload_unconfirmed"):
        asyncio.run(
            transport.deliver(message, DeliverableMedia(media_path, "video"))
        )


def test_delivery_builds_request_with_the_same_upload_deadline():
    transport = TelegramDeliveryTransport(local_mode=True, timeout_seconds=1800)

    request = transport.request

    assert request._media_write_timeout == 1800
    assert request._client.timeout.read == 1800
    assert request._client.timeout.write == 1800

