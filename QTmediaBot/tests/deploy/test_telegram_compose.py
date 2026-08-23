from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_local_bot_api_uses_pinned_timeout_fixed_build():
    compose = (PROJECT_ROOT / "deploy/telegram/compose.yaml").read_text(
        encoding="utf-8"
    )

    assert "dockerfile: deploy/telegram/bot-api/Dockerfile" in compose
    assert "TELEGRAM_BOT_API_COMMIT:" in compose
    assert "TELEGRAM_BOT_API_IDLE_TIMEOUT_SECONDS: ${" in compose
    assert ":-7200}" in compose


def test_telegram_bot_uses_eight_fragment_candidate():
    compose = (PROJECT_ROOT / "deploy/telegram/compose.yaml").read_text(
        encoding="utf-8"
    )

    assert (
        "PRIVATE_SEARCH_CONCURRENT_FRAGMENTS: "
        "${PRIVATE_SEARCH_CONCURRENT_FRAGMENTS:-8}"
    ) in compose
