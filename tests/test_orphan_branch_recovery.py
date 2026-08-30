import command_menu
import fight_patterns
import runtime_bootstrap


def test_recovered_direct_hostility_patterns_match_lost_cases():
    hostile = (
        "ублюдок",
        "мразь ты",
        "гнида",
        "тупорылый",
        "безмозглый",
        "говнюк",
        "уёбок",
        "шавка",
        "закрой ебало",
        "отъебись",
        "ты клоун",
        "ну ты и баран",
        "собака ты",
        "ты крыса",
        "ты свинья",
        "ты козёл",
        "ты осёл",
        "ты бомж",
        "ты нищий",
        "днище",
    )
    for text in hostile:
        assert fight_patterns.EXTRA_FIGHT_RE.search(text), text


def test_recovered_ambiguous_words_do_not_flag_ordinary_sentences():
    ordinary = (
        "у меня собака заболела",
        "в цирке выступает клоун",
        "на ферме живёт баран",
        "крыса пробежала по подвалу",
        "свинья весит сто килограммов",
        "козёл стоит у забора",
    )
    for text in ordinary:
        assert not fight_patterns.EXTRA_FIGHT_RE.search(text), text


def test_social_debug_is_owner_only_menu_surface():
    owner_names = command_menu.command_names(command_menu.OWNER_COMMANDS)
    group_names = command_menu.command_names(command_menu.GROUP_COMMANDS)
    private_names = command_menu.command_names(command_menu.PRIVATE_COMMANDS)

    assert "social_debug" in owner_names
    assert "social_debug" not in group_names
    assert "social_debug" not in private_names


def test_social_debug_uses_current_social_owner_in_bootstrap():
    order = runtime_bootstrap.RUNTIME_LOAD_ORDER
    social = order.index("social_priority_runtime")
    diagnostics = order.index("owner_social_diagnostics_runtime")
    conflict = order.index("conflict_fsm_runtime")

    assert social < diagnostics < conflict
