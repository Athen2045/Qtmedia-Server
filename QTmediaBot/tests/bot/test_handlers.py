import asyncio
from unittest.mock import AsyncMock, call

from qtmedia_bot.bot.config import BotSettings
from qtmedia_bot.bot.handlers import messages as message_handlers
from qtmedia_bot.bot.handlers.callbacks import quality_selected
from qtmedia_bot.bot.handlers.commands import cancel, help_command, start
from qtmedia_bot.bot.services.inspection import MediaInspection
from qtmedia_bot.bot.services.jobs import JobCatalog
from qtmedia_bot.bot.services.quality import QualityOption
from qtmedia_bot.bot.services.source_policy import SourcePolicyError


class FakeMessage:
    def __init__(self, chat_type="private", user_id=123, text="hello"):
        self.chat = type("Chat", (), {"type": chat_type, "id": 456})()
        self.from_user = type("User", (), {"id": user_id})()
        self.text = text
        self.reply_text = AsyncMock()


class FakeUpdate:
    def __init__(self, message):
        self.effective_message = message
        self.effective_user = message.from_user


class FakeContext:
    def __init__(
        self,
        settings=None,
        jobs=None,
        downloads=None,
        admission=None,
    ):
        self.user_data = {}
        self.bot = type("Bot", (), {"delete_message": AsyncMock()})()
        self.application = type(
            "Application",
            (),
            {
                "bot_data": {
                    "settings": settings,
                    "jobs": jobs,
                    "downloads": downloads,
                    "admission": admission,
                },
                "bot": self.bot,
            },
        )()


def test_start_replies_with_welcome_and_keyboard():
    message = FakeMessage()

    asyncio.run(start(FakeUpdate(message), FakeContext()))

    message.reply_text.assert_awaited_once()
    assert message.reply_text.await_args.kwargs["reply_markup"] is not None


def test_help_and_cancel_reply_in_private_chat():
    message = FakeMessage()
    update = FakeUpdate(message)

    async def exercise_handlers():
        await help_command(update, FakeContext())
        await cancel(update, FakeContext())

    asyncio.run(exercise_handlers())

    assert message.reply_text.await_count == 2


def test_text_message_gives_guidance_without_starting_a_download():
    message = FakeMessage(text="https://example.com/media")

    asyncio.run(message_handlers.text_message(FakeUpdate(message), FakeContext()))

    message.reply_text.assert_awaited_once()
    assert "download" in message.reply_text.await_args.args[0].casefold()


def bot_settings():
    return BotSettings(
        token="test-token",
        base_url="https://api.example/bot",
        file_base_url="https://api.example/file/bot",
        local_mode=False,
        private_chats_only=True,
        allowed_user_ids=frozenset({123}),
        allowed_domains=frozenset({"example.com"}),
        max_upload_bytes=4_000_000,
        max_duration_seconds=120,
    )


def inspection():
    return MediaInspection(
        url="https://example.com/video",
        title="Example title",
        duration_seconds=30,
        formats=(),
    )


def quality_option():
    return QualityOption("v720", "720p", 720, 1_000_000, False, "720", "video")


def test_allowed_link_inspection_sends_inline_quality_menu(monkeypatch):
    monkeypatch.setattr(
        message_handlers, "inspect_source", lambda url, settings: inspection()
    )

    async def fake_to_thread(function, *args):
        return function(*args)

    monkeypatch.setattr(message_handlers.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(
        message_handlers,
        "build_quality_options",
        lambda formats, max_output_bytes, best_available_size_bytes=None: (
            quality_option(),
        ),
    )
    message = FakeMessage(text="https://example.com/video")
    context = FakeContext(bot_settings(), JobCatalog(ttl_seconds=600))

    asyncio.run(message_handlers.text_message(FakeUpdate(message), context))

    assert message.reply_text.await_count == 2
    assert message.reply_text.await_args.kwargs["reply_markup"] is not None


def test_allowed_link_inspection_passes_metadata_to_quality_builder(monkeypatch):
    inspected = MediaInspection(
        url="https://example.com/video",
        title="Example title",
        duration_seconds=30,
        formats=(
            {
                "format_id": "720",
                "height": 720,
                "vcodec": "avc1",
                "acodec": "mp4a",
                "filesize": 1_000_000,
            },
        ),
    )
    monkeypatch.setattr(
        message_handlers, "inspect_source", lambda url, settings: inspected
    )

    async def fake_to_thread(function, *args):
        return function(*args)

    monkeypatch.setattr(message_handlers.asyncio, "to_thread", fake_to_thread)
    message = FakeMessage(text="https://example.com/video")
    context = FakeContext(bot_settings(), JobCatalog(ttl_seconds=600))

    asyncio.run(message_handlers.text_message(FakeUpdate(message), context))

    assert message.reply_text.await_count == 2
    assert message.reply_text.await_args.kwargs["reply_markup"] is not None


def test_new_link_is_rejected_while_user_has_an_active_job(monkeypatch):
    jobs = JobCatalog(ttl_seconds=600)
    active_job = jobs.create(123, 456, inspection(), (quality_option(),))
    assert jobs.claim_for_user(active_job, 123, 456, "v720") is not None
    monkeypatch.setattr(
        message_handlers,
        "inspect_source",
        lambda url, settings: (_ for _ in ()).throw(
            AssertionError("should not inspect")
        ),
    )
    message = FakeMessage(text="https://example.com/another-video")

    asyncio.run(
        message_handlers.text_message(
            FakeUpdate(message), FakeContext(bot_settings(), jobs)
        )
    )

    assert message.reply_text.await_count == 1
    assert "active" in message.reply_text.await_args.args[0].casefold()


def test_invalid_link_returns_generic_policy_message(monkeypatch):
    def reject(url, settings):
        raise SourcePolicyError(
            "unsupported_domain", "This source is not supported by the bot."
        )

    monkeypatch.setattr(message_handlers, "inspect_source", reject)
    message = FakeMessage(text="https://other.example/video")

    asyncio.run(
        message_handlers.text_message(
            FakeUpdate(message), FakeContext(bot_settings(), JobCatalog())
        )
    )

    assert message.reply_text.await_count == 2
    assert "supported" in message.reply_text.await_args.args[0].casefold()
    assert "other.example" not in message.reply_text.await_args.args[0]


class FakeCallbackQuery:
    def __init__(self, user_id, data, message_id=654):
        self.data = data
        self.from_user = type("User", (), {"id": user_id})()
        self.message = type(
            "Message",
            (),
            {
                "chat": type("Chat", (), {"type": "private", "id": 456})(),
                "message_id": message_id,
            },
        )()
        self.message.reply_text = AsyncMock()
        self.answer = AsyncMock()
        self.edit_message_text = AsyncMock()


class FakeCallbackUpdate:
    def __init__(self, query):
        self.callback_query = query
        self.effective_user = query.from_user
        self.effective_message = query.message


class FakeDownloadManager:
    def __init__(self):
        self.calls = []

    async def run(self, record, selected_option, message, progress_reporter=None):
        self.calls.append((record, selected_option, message, progress_reporter))


def test_owned_quality_callback_starts_download(monkeypatch):
    jobs = JobCatalog(ttl_seconds=600)
    selected = quality_option()
    job_id = jobs.create(123, 456, inspection(), (selected,))
    query = FakeCallbackQuery(123, f"quality:{job_id}:v720")
    manager = FakeDownloadManager()

    asyncio.run(
        quality_selected(
            FakeCallbackUpdate(query), FakeContext(bot_settings(), jobs, manager)
        )
    )

    assert len(manager.calls) == 1
    assert manager.calls[0][1] == selected
    assert "started" in query.answer.await_args.args[0].casefold()


def test_quality_callback_passes_a_progress_reporter_to_download_manager():
    jobs = JobCatalog(ttl_seconds=600)
    selected = quality_option()
    job_id = jobs.create(123, 456, inspection(), (selected,))
    query = FakeCallbackQuery(123, f"quality:{job_id}:v720")
    manager = FakeDownloadManager()

    asyncio.run(
        quality_selected(
            FakeCallbackUpdate(query), FakeContext(bot_settings(), jobs, manager)
        )
    )

    reporter = manager.calls[0][3]
    assert reporter is not None
    assert reporter._label == "720p"


def test_successful_quality_callback_deletes_all_transient_status_messages():
    jobs = JobCatalog(ttl_seconds=600)
    selected = quality_option()
    job_id = jobs.create(
        123,
        456,
        inspection(),
        (selected,),
        inspection_message_id=987,
    )
    query = FakeCallbackQuery(123, f"quality:{job_id}:v720")
    manager = FakeDownloadManager()
    context = FakeContext(bot_settings(), jobs, manager)

    asyncio.run(quality_selected(FakeCallbackUpdate(query), context))

    assert context.bot.delete_message.await_args_list == [
        call(chat_id=456, message_id=987),
        call(chat_id=456, message_id=654),
    ]
    assert all(
        "Uploaded" not in call.args[0]
        for call in query.edit_message_text.await_args_list
    )


def test_cancel_command_requests_download_cancellation():
    class CancelManager:
        def __init__(self):
            self.calls = []

        def cancel_for_user(self, user_id, chat_id):
            self.calls.append((user_id, chat_id))
            return True

    message = FakeMessage(text="/cancel")
    manager = CancelManager()
    context = FakeContext(bot_settings(), JobCatalog(), manager)

    asyncio.run(cancel(FakeUpdate(message), context))

    assert manager.calls == [(123, 456)]


def test_cancel_command_clears_unselected_quality_job():
    jobs = JobCatalog(ttl_seconds=600)
    job_id = jobs.create(123, 456, inspection(), (quality_option(),))
    message = FakeMessage(text="/cancel")

    asyncio.run(cancel(FakeUpdate(message), FakeContext(bot_settings(), jobs)))

    assert jobs.get_for_user(job_id, 123, 456).status == "cancelled"
    assert jobs.current_for_user(123, 456) is None


def test_cancel_button_clears_unselected_quality_job():
    jobs = JobCatalog(ttl_seconds=600)
    job_id = jobs.create(123, 456, inspection(), (quality_option(),))
    message = FakeMessage(text="Cancel")

    asyncio.run(
        message_handlers.text_message(
            FakeUpdate(message), FakeContext(bot_settings(), jobs)
        )
    )

    assert jobs.get_for_user(job_id, 123, 456).status == "cancelled"


def test_foreign_quality_callback_is_rejected_without_exposing_url():
    jobs = JobCatalog(ttl_seconds=600)
    job_id = jobs.create(123, 456, inspection(), (quality_option(),))
    query = FakeCallbackQuery(999, f"quality:{job_id}:v720")

    asyncio.run(
        quality_selected(FakeCallbackUpdate(query), FakeContext(bot_settings(), jobs))
    )

    query.answer.assert_awaited_once()
    assert "not authorized" in query.answer.await_args.args[0].casefold()
    assert "example.com" not in query.answer.await_args.args[0]


def test_search_text_is_treated_as_non_url_guidance():
    message = FakeMessage(text="Search")
    context = FakeContext(bot_settings(), JobCatalog())

    asyncio.run(message_handlers.text_message(FakeUpdate(message), context))

    assert context.user_data == {}
    response = message.reply_text.await_args.args[0].casefold()
    assert "supported media link" in response
    assert "search" not in response


class RejectingAdmission:
    def allow_request(self, user_id):
        return False

    def try_enter_queue(self, job_id):
        return False

    def leave_queue(self, job_id):
        return None


def test_rate_limit_rejects_direct_inspection_before_source_work(monkeypatch):
    monkeypatch.setattr(
        message_handlers,
        "inspect_source",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not inspect")),
    )
    message = FakeMessage(text="https://example.com/video")
    context = FakeContext(
        bot_settings(),
        JobCatalog(),
        admission=RejectingAdmission(),
    )

    asyncio.run(message_handlers.text_message(FakeUpdate(message), context))

    assert "too many" in message.reply_text.await_args.args[0].casefold()


def test_full_transfer_queue_releases_claim_and_returns_busy_message():
    jobs = JobCatalog(ttl_seconds=600)
    selected = quality_option()
    job_id = jobs.create(123, 456, inspection(), (selected,))
    query = FakeCallbackQuery(123, f"quality:{job_id}:v720")
    manager = FakeDownloadManager()

    asyncio.run(
        quality_selected(
            FakeCallbackUpdate(query),
            FakeContext(
                bot_settings(),
                jobs,
                manager,
                admission=RejectingAdmission(),
            ),
        )
    )

    assert manager.calls == []
    assert jobs.current_for_user(123, 456) is None
    assert "busy" in query.answer.await_args.args[0].casefold()

