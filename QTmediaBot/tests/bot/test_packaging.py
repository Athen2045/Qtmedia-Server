import tomllib
from pathlib import Path


def test_project_declares_telegram_bot_runtime_and_entrypoint():
    project_root = Path(__file__).resolve().parents[2]
    project = tomllib.loads(
        (project_root / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]

    assert "python-telegram-bot==22.6" in project["dependencies"]
    assert "python-dotenv>=1.0" in project["dependencies"]
    assert project["scripts"]["qtmedia-bot"] == (
        "qtmedia_bot.bot.application:main"
    )

