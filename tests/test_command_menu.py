import command_menu


def test_group_menu_is_exactly_the_approved_compact_list():
    assert command_menu.command_names(command_menu.GROUP_COMMANDS) == (
        "stickers",
        "roast",
        "wisdom",
        "nickname",
        "nickname_off",
        "whoami",
        "title",
        "title_status",
        "judge",
        "argument",
        "debate",
        "leaderboard",
        "awards",
        "chat_native_status",
    )


def test_private_menu_hides_group_entertainment_clutter():
    names = set(command_menu.command_names(command_menu.PRIVATE_COMMANDS))
    assert {"start", "help", "settings", "search", "stickers"} <= names
    assert {"roast", "title", "title_status", "duel", "awards", "leaderboard"}.isdisjoint(names)


def test_owner_menu_contains_every_operational_and_diagnostic_command():
    owner = set(command_menu.command_names(command_menu.OWNER_COMMANDS))
    assert set(command_menu.command_names(command_menu.GROUP_COMMANDS)) <= owner
    assert set(command_menu.command_names(command_menu.PRIVATE_COMMANDS)) <= owner
    assert {
        "stats",
        "geminiversion",
        "hard_on",
        "hard_off",
        "hard_status",
        "hard_level",
        "hard_stats",
        "people",
        "set_archetype",
        "week_auto_on",
        "week_auto_off",
        "week_auto_status",
        "week_time",
    } <= owner


def test_all_menus_respect_telegram_limits_and_have_unique_commands():
    for commands in (
        command_menu.GROUP_COMMANDS,
        command_menu.PRIVATE_COMMANDS,
        command_menu.OWNER_COMMANDS,
    ):
        assert len(commands) <= 100
        names = command_menu.command_names(commands)
        assert len(names) == len(set(names))
        for command, description in commands:
            assert 1 <= len(command) <= 32
            assert 1 <= len(description) <= 256
