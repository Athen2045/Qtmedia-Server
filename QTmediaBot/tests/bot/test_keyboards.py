from qtmedia_bot.bot.keyboards.main import main_menu


def test_main_menu_exposes_only_initial_actions():
    keyboard = main_menu()
    labels = [button.text for row in keyboard.keyboard for button in row]

    assert labels == ["Download link", "Cancel"]

