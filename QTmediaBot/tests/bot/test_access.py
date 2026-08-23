from qtmedia_bot.bot.access import is_private_chat, is_user_allowed


def test_private_chat_check_accepts_only_private_chats():
    assert is_private_chat("private") is True
    assert is_private_chat("group") is False
    assert is_private_chat("supergroup") is False
    assert is_private_chat("channel") is False
    assert is_private_chat(None) is False


def test_empty_allowlist_allows_any_present_user():
    assert is_user_allowed(123, frozenset()) is True


def test_configured_allowlist_rejects_missing_or_foreign_users():
    allowed = frozenset({123})

    assert is_user_allowed(123, allowed) is True
    assert is_user_allowed(456, allowed) is False
    assert is_user_allowed(None, allowed) is False

