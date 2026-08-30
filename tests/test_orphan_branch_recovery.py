import command_menu
import conflict_fsm_runtime
import fight_patterns
import runtime_bootstrap


def _production_extra_hostile(text: str) -> bool:
    """Mirror the conflict-FSM + Fight Routing v3 detector union."""
    return bool(
        conflict_fsm_runtime.EXTRA_HOSTILE_RE.search(text)
        or fight_patterns.EXTRA_FIGHT_RE.search(text)
    )


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
        assert _production_extra_hostile(text), text


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
        assert not _production_extra_hostile(text), text


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
