from qtmedia_bot.bot.messages import cancel_text, help_text, welcome_text


def test_welcome_text_explains_temporary_processing_and_lawful_use():
    text = welcome_text()

    assert "temporarily" in text
    assert "deleted" in text
    assert "allowed to access" in text


def test_onboarding_describes_only_the_direct_download_flow():
    for text in (welcome_text(), help_text()):
        assert "supported media link" in text.casefold()
        assert "search" not in text.casefold()


def test_help_and_cancel_text_are_nonempty_and_do_not_contain_secrets():
    assert help_text().strip()
    assert cancel_text().strip()
    for text in (help_text(), cancel_text()):
        assert "TELEGRAM_BOT_TOKEN" not in text

