import logging

import httpx

from qtmedia_bot.bot.logging_utils import configure_private_logging


def test_private_logging_redacts_urls_and_configured_secrets(caplog):
    url = "https://private.example/media?id=123"
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abc"

    with caplog.at_level(logging.INFO, logger="qtmedia_bot.bot.test"):
        configure_private_logging((token,))
        logging.getLogger("qtmedia_bot.bot.test").info(
            "Requested %s using %s", url, token
        )

    assert url not in caplog.text
    assert token not in caplog.text
    assert "[redacted-url]" in caplog.text
    assert "[redacted-secret]" in caplog.text


def test_private_logging_redacts_sensitive_httpx_url_arguments(caplog):
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abc"
    request_url = httpx.URL(f"http://local.test/bot{token}/getMe")

    with caplog.at_level(logging.INFO, logger="httpx"):
        configure_private_logging((token,))
        logging.getLogger("httpx").info(
            "HTTP Request: %s %s", "POST", request_url
        )

    assert token not in caplog.text
    assert "local.test" not in caplog.text
    assert "[redacted-url]" in caplog.text

