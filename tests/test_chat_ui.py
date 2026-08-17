from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from rich.console import Console

from private_search.ai.actions import AgentAction
from private_search.ai.chat import ChatTurnResult, ContextUsage
from private_search.ai.tools import ToolResult
from private_search.app.chat_ui import (
    LocalCommand,
    _format_blackbird_metadata,
    execute_local_command,
    interactive_chat,
    parse_local_command,
    render_chat_result,
    select_project_image,
)


class FakeChat:
    def __init__(self):
        self.downloads = []

    def execute_action(self, action):
        self.downloads.append(action)
        return ToolResult(action.action, True, "Download complete.")


def test_parse_local_command_maps_exit_aliases():
    assert parse_local_command("/q") == LocalCommand("quit", "")
    assert parse_local_command("/exit") == LocalCommand("quit", "")
    assert parse_local_command("ordinary text") is None


def test_help_and_legacy_image_commands_are_removed():
    console = Console(record=True)

    assert execute_local_command(LocalCommand("help"), console) is True
    assert "/image" not in console.export_text()
    assert "clear-image" not in console.export_text()

    for name in ("image", "clear-image"):
        command_console = Console(record=True)
        assert execute_local_command(LocalCommand(name), command_console) is True
        assert "Unknown command" in command_console.export_text()


def test_select_project_image_returns_none_for_empty_folder(monkeypatch, tmp_path):
    monkeypatch.setattr("private_search.app.chat_ui.config.PROJECT_ROOT", tmp_path)
    console = Console(record=True)

    assert select_project_image(console) is None
    assert "No supported images" in console.export_text()


def test_select_project_image_automatically_selects_one_candidate(monkeypatch, tmp_path):
    image = tmp_path / "image" / "nested" / "sample.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image")
    monkeypatch.setattr("private_search.app.chat_ui.config.PROJECT_ROOT", tmp_path)
    console = Console(record=True)

    assert select_project_image(console) == str(image.resolve())
    assert "nested/sample.jpg" in console.export_text()


def test_select_project_image_prompts_for_multiple_candidates_and_previews(
    monkeypatch, tmp_path
):
    first = tmp_path / "image" / "a.jpg"
    second = tmp_path / "image" / "nested" / "b.PNG"
    second.parent.mkdir(parents=True)
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    monkeypatch.setattr("private_search.app.chat_ui.config.PROJECT_ROOT", tmp_path)
    previews = []
    monkeypatch.setattr(
        "private_search.app.chat_ui.render_local_image",
        lambda path: previews.append(path) or False,
    )
    monkeypatch.setattr(
        "private_search.app.chat_ui.Prompt.ask", lambda *args, **kwargs: "2"
    )
    console = Console(record=True)

    assert select_project_image(console) == str(second.resolve())
    assert previews == [first.resolve(), second.resolve()]
    output = console.export_text()
    assert "1" in output and "a.jpg" in output
    assert "2" in output and "nested/b.PNG" in output


def test_select_project_image_retries_invalid_choice_and_allows_cancel(
    monkeypatch, tmp_path
):
    first = tmp_path / "image" / "a.jpg"
    second = tmp_path / "image" / "b.jpg"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    monkeypatch.setattr("private_search.app.chat_ui.config.PROJECT_ROOT", tmp_path)
    choices = iter(["invalid", "q"])
    monkeypatch.setattr(
        "private_search.app.chat_ui.Prompt.ask", lambda *args, **kwargs: next(choices)
    )
    console = Console(record=True)

    assert select_project_image(console) is None
    assert "Choose a number" in console.export_text()


def test_select_project_image_rejects_zero_and_negative_choices(monkeypatch, tmp_path):
    first = tmp_path / "image" / "a.jpg"
    second = tmp_path / "image" / "b.jpg"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    monkeypatch.setattr("private_search.app.chat_ui.config.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("private_search.app.chat_ui.render_local_image", lambda path: False)
    choices = iter(["0", "-1", "1"])
    monkeypatch.setattr(
        "private_search.app.chat_ui.Prompt.ask", lambda *args, **kwargs: next(choices)
    )
    console = Console(record=True)

    assert select_project_image(console) == str(first.resolve())
    assert console.export_text().count("Choose a number") == 2


def test_select_project_image_cancels_on_empty_input(monkeypatch, tmp_path):
    first = tmp_path / "image" / "a.jpg"
    second = tmp_path / "image" / "b.jpg"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    monkeypatch.setattr("private_search.app.chat_ui.config.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("private_search.app.chat_ui.Prompt.ask", lambda *args, **kwargs: "")
    console = Console(record=True)

    assert select_project_image(console) is None
    assert "Selected image" not in console.export_text()


def test_readme_documents_project_image_folder_and_not_legacy_commands():
    readme = Path(__file__).resolve().parents[1] / "README.md"
    content = readme.read_text(encoding="utf-8")

    assert "/image PATH" not in content
    assert "/clear-image" not in content
    assert "active image path" not in content.casefold()
    assert "project `image` folder" in content
    assert "Kitty-optional previews" in content


def test_execute_local_command_returns_false_for_quit():
    console = Console(record=True)

    assert execute_local_command(LocalCommand("quit", ""), console) is False


def test_about_command_shows_theia_identity_and_tool_safeguards():
    console = Console(record=True)

    assert execute_local_command(LocalCommand("about", ""), console) is True

    output = console.export_text()
    assert "Theia" in output
    assert "confirmation" in output.casefold()
    assert "shell" in output.casefold()
    assert "security-analyst" in output
    assert "No flirtation" in output
    assert "flirtatious" not in output.casefold()


def test_thinking_and_context_commands_control_and_report_runtime_state():
    class RuntimeChat:
        thinking_enabled = True
        context_usage = ContextUsage(used=1234, remaining=6958, total=8192, exact=True)

        def set_thinking(self, enabled):
            self.thinking_enabled = enabled

    chat = RuntimeChat()
    console = Console(record=True, width=100)

    assert execute_local_command(LocalCommand("thinking", "off"), console, chat) is True
    assert chat.thinking_enabled is False
    assert execute_local_command(LocalCommand("context"), console, chat) is True
    assert execute_local_command(LocalCommand("options"), console, chat) is True

    output = console.export_text()
    assert "Thinking mode: off" in output
    assert "1,234 / 8,192" in output
    assert "6,958" in output
    assert "llama.cpp" in output


def test_theia_message_uses_a_side_label_instead_of_a_panel():
    result = ChatTurnResult(
        user_text="hello",
        assistant_text="Hello from Theia.",
    )
    console = Console(record=True, width=60)

    render_chat_result(result, console)

    output = console.export_text()
    assert "Theia:" in output
    assert "Theia: Hello from Theia." in output
    assert "╭" not in output


def test_search_results_prompt_for_a_title_and_download_the_selected_result(monkeypatch):
    result = ChatTurnResult(
        user_text="Search for Bimbo PMV",
        action=AgentAction(
            action="refine_search",
            reason="The user requested a search.",
            query="Bimbo PMV",
        ),
        tool_result=ToolResult(
            "refine_search",
            True,
            "Found 2 search result(s).",
            data=[
                SimpleNamespace(
                    title="First result",
                    site="Example",
                    view_count=10,
                    max_height=720,
                    url="https://example.test/first",
                ),
                SimpleNamespace(
                    title="Second result",
                    site="Example",
                    view_count=20,
                    max_height=1080,
                    url="https://example.test/second",
                ),
            ],
        ),
        assistant_text="Found 2 search result(s).",
    )
    chat = FakeChat()
    console = Console(record=True)
    prompts = []

    def choose_result(question, **_kwargs):
        prompts.append(question)
        return "2"

    monkeypatch.setattr("private_search.app.chat_ui.Prompt.ask", choose_result)

    render_chat_result(result, console, chat=chat)

    assert len(chat.downloads) == 1
    assert chat.downloads[0].action == "download_media"
    assert chat.downloads[0].url == "https://example.test/second"
    assert prompts == ["Download result [1-2], or press Enter to skip"]
    assert "Theia" in console.export_text()


def test_reverse_image_results_render_as_a_table():
    result = ChatTurnResult(
        user_text="Reverse search this image",
        action=AgentAction(
            action="reverse_image_search",
            reason="The user requested reverse search.",
            image_path="C:/image.jpg",
        ),
        tool_result=ToolResult(
            "reverse_image_search",
            True,
            "Found 1 reverse-image result(s).",
            data=[
                {
                    "name": "Example #1",
                    "url": "https://example.test/result",
                    "similarity": "0.91",
                    "artist": "Artist",
                    "site": "Example",
                }
            ],
        ),
        assistant_text="Found 1 reverse-image result(s).",
    )
    console = Console(record=True, width=100)

    render_chat_result(result, console)

    output = console.export_text()
    assert "Reverse-image results (1)" in output
    assert "Example #1" in output
    assert "91.0% (Accurate)" in output
    assert "https://example.test/result" in output


def test_blackbird_username_results_render_normalized_records():
    result = ChatTurnResult(
        user_text="Check username alice",
        action=AgentAction(
            action="username_osint",
            reason="The user requested username OSINT.",
            username="alice",
        ),
        tool_result=ToolResult(
            "username_osint",
            True,
            "Found 1 username result(s).",
            data=[
                {
                    "source": "blackbird",
                    "kind": "username",
                    "site": "GitHub",
                    "url": "https://github.com/alice",
                    "status": "FOUND",
                    "category": "social",
                    "metadata": ["profile"],
                }
            ],
        ),
        assistant_text="Found 1 username result(s).",
    )
    console = Console(record=True, width=120)

    render_chat_result(result, console)

    output = console.export_text()
    assert "Blackbird username results (1)" in output
    assert "GitHub" in output
    assert "FOUND" in output
    assert "https://github.com/alice" in output


def test_blackbird_email_results_render_normalized_records_safely():
    result = ChatTurnResult(
        user_text="Check alice@example.com",
        action=AgentAction(
            action="email_osint",
            reason="The user requested email OSINT.",
            email="alice@example.com",
        ),
        tool_result=ToolResult(
            "email_osint",
            True,
            "Found 1 email result(s).",
            data=[
                {
                    "source": "blackbird",
                    "kind": "email",
                    "site": "Example",
                    "url": "https://example.test/alice",
                    "status": "UNKNOWN",
                    "category": None,
                    "metadata": [{"label": "breach"}, "alias"],
                }
            ],
        ),
        assistant_text="Found 1 email result(s).",
    )
    console = Console(record=True, width=120)

    render_chat_result(result, console)

    output = console.export_text()
    assert "Blackbird email results (1)" in output
    assert "Example" in output
    assert "UNKNOWN" in output
    assert "https://example.test/alice" in output


def test_blackbird_metadata_limits_rendered_items_for_strings_and_dicts():
    metadata = [
        "alias",
        {"label": "country", "value": "US"},
        {"label": "breach"},
        "mirror",
        {"value": "shadow"},
    ]

    assert _format_blackbird_metadata(metadata) == "alias; country: US; breach"


def test_interactive_chat_wires_blackbird_for_username_and_email(monkeypatch):
    events: list[tuple[str, object]] = []

    class FakeServer:
        def __init__(self, settings):
            events.append(("server_init", settings))
            self.server_url = "http://127.0.0.1:8080"

        def start(self):
            events.append(("server_start", None))

        def stop(self):
            events.append(("server_stop", None))

    class FakeBlackbirdAdapter:
        def __init__(self):
            events.append(("blackbird_adapter", self))

    class FakeFaceAssistedReverseImageAdapter:
        def __init__(self):
            events.append(("face_assisted_adapter", self))

    class FakeToolRegistry:
        def __init__(self, confirmation, **kwargs):
            events.append(("tool_registry", kwargs))

    class FakeChatOrchestrator:
        def __init__(self, client, registry, **kwargs):
            events.append(("chat_init", registry))
            events.append(("chat_kwargs", kwargs))

    monkeypatch.setattr(
        "private_search.app.chat_ui.RuntimeSettings.from_environment",
        lambda: SimpleNamespace(context_size=8192),
    )
    monkeypatch.setattr("private_search.app.chat_ui.LlamaServer", FakeServer)
    monkeypatch.setattr("private_search.app.chat_ui.LlamaClient", lambda server_url: ("client", server_url))
    monkeypatch.setattr(
        "private_search.app.chat_ui.FaceAssistedReverseImageAdapter",
        FakeFaceAssistedReverseImageAdapter,
    )
    monkeypatch.setattr("private_search.app.chat_ui.BlackbirdAdapter", FakeBlackbirdAdapter)
    monkeypatch.setattr("private_search.app.chat_ui.ToolRegistry", FakeToolRegistry)
    monkeypatch.setattr("private_search.app.chat_ui.ChatOrchestrator", FakeChatOrchestrator)
    monkeypatch.setattr("private_search.app.chat_ui.Prompt.ask", lambda *args, **kwargs: "/quit")

    interactive_chat()

    registry_kwargs = next(value for key, value in events if key == "tool_registry")
    assert isinstance(registry_kwargs["reverse_image_tool"], FakeFaceAssistedReverseImageAdapter)
    assert isinstance(registry_kwargs["username_osint_tool"], FakeBlackbirdAdapter)
    assert isinstance(registry_kwargs["email_osint_tool"], FakeBlackbirdAdapter)
    assert callable(registry_kwargs["reverse_image_resolver"])
    assert next(value for key, value in events if key == "chat_kwargs") == {
        "context_window": 8192
    }
    assert ("server_stop", None) in events
