from qtmedia_bot.bot.keyboards.quality import quality_menu
from qtmedia_bot.bot.services.quality import QualityOption


def test_quality_keyboard_contains_one_opaque_callback_per_option():
    options = (
        QualityOption("v1080", "1080p", 1080, 2_000_000, False, "1080", "video"),
        QualityOption("mp3", "MP3", None, None, False, "audio", "audio"),
    )

    keyboard = quality_menu("job123", options)
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert [button.text for button in buttons] == ["1080p — 1.9 MB", "MP3 — size unknown"]
    assert [button.callback_data for button in buttons] == [
        "quality:job123:v1080",
        "quality:job123:mp3",
    ]
    assert all("example.com" not in button.callback_data for button in buttons)

