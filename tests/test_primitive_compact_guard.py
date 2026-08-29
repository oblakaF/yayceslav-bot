import primitive_compact_guard as guard


def test_simple_arithmetic_is_compact():
    assert guard.should_force_primitive_compact("2+2")
    assert guard.should_force_primitive_compact("5 + 5")
    assert guard.should_force_primitive_compact("9*99")
    assert guard.should_force_primitive_compact("12 × 8")


def test_bare_number_or_date_is_not_treated_as_arithmetic():
    assert not guard.should_force_primitive_compact("42")
    assert not guard.should_force_primitive_compact("2026-08-18")


def test_short_interjections_are_compact():
    assert guard.should_force_primitive_compact("Э")
    assert guard.should_force_primitive_compact("ну")
    assert guard.should_force_primitive_compact("чё?")
    assert guard.should_force_primitive_compact("алё")


def test_real_question_is_not_collapsed_just_because_it_is_short():
    assert not guard.should_force_primitive_compact("что такое интеграл?")
    assert not guard.should_force_primitive_compact("почему не работает?")
    assert not guard.should_force_primitive_compact("объясни 2+2")


def test_serious_short_message_is_not_compacted():
    assert not guard.should_force_primitive_compact("болит")
    assert not guard.should_force_primitive_compact("пожар")


def test_private_memory_wrapper_uses_latest_message_only():
    contents = (
        "Ниже история текущей задачи.\n"
        "Пользователь: расскажи подробно про математику\n"
        "Новое сообщение пользователя:\n"
        "5+5"
    )
    assert guard.latest_user_text(contents) == "5+5"
    assert guard.should_force_primitive_compact(contents)


def test_group_memory_wrapper_uses_latest_message_only():
    contents = (
        "Ниже переписка группы.\n"
        "Кто-то: длинный разговор ни о чём\n"
        "Новое обращение к тебе от Вася:\n"
        "Э"
    )
    assert guard.latest_user_text(contents) == "Э"
    assert guard.should_force_primitive_compact(contents)


def test_primitive_output_is_hard_capped_without_hostile_canned_replacement():
    source = (
        "10. Ты решил проверить калькулятор. "
        "Потом я расскажу тебе историю на пять абзацев. "
        "И ещё один совершенно лишний абзац."
    )
    result = guard.truncate_primitive_text(source)
    assert len(result) <= guard.PRIMITIVE_MAX_CHARS
    assert result.startswith("10.")
    assert "Пошёл нахуй" not in result
    assert "Завали ебало" not in result
