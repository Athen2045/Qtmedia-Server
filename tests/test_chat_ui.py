from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from rich.console import Console

from private_search.ai.actions import AgentAction
from private_search.ai.chat import ChatTurnResult
from private_search.ai.tools import ToolResult
from private_search.app.chat_ui import (
    LocalCommand,
    execute_local_command,
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
    chat = FakeChat()
    console = Console(record=True)

    assert execute_local_command(LocalCommand("help"), chat, console) is True
    assert "/image" not in console.export_text()
    assert "clear-image" not in console.export_text()

    for name in ("image", "clear-image"):
        command_console = Console(record=True)
        assert execute_local_command(LocalCommand(name), chat, command_console) is True
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
    chat = FakeChat()
    console = Console(record=True)

    assert execute_local_command(LocalCommand("quit", ""), chat, console) is False


def test_about_command_shows_theia_identity_and_tool_safeguards():
    chat = FakeChat()
    console = Console(record=True)

    assert execute_local_command(LocalCommand("about", ""), chat, console) is True

    output = console.export_text()
    assert "Theia" in output
    assert "confirmation" in output.casefold()
    assert "shell" in output.casefold()
    assert "security-analyst" in output
    assert "No flirtation" in output
    assert "flirtatious" not in output.casefold()


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
    assert "https://example.test/result" in output
