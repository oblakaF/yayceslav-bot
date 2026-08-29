import fight_routing_v3 as v3


def test_current_turn_ignores_old_serious_context():
    prompt = (
        "Камень-Дрочер: Собака уже умерла\n"
        "Яйцеслав: Искренне сочувствую.\n\n"
        "Новое обращение к тебе от Серега Джус:\n"
        "Ебани лучше какой-нибудь анекдот"
    )

    assert v3.current_turn_text(prompt) == "Ебани лучше какой-нибудь анекдот"


def test_current_turn_drops_search_results_for_tone():
    prompt = (
        "Новое обращение к тебе от Серега Джус:\n"
        "проверь концерт Б.А.У.\n\n"
        "Результаты поиска:\n"
        "ONYX — 24 сентября"
    )

    assert v3.current_turn_text(prompt) == "проверь концерт Б.А.У."


def test_live_fight_bait_variants_are_detected():
    samples = (
        "Ты пиздабол",
        "Ну ты и залупа",
        "Хуй будешь нюхать?",
        "По факту метнулся к хую и нюхаешь",
        "Ты нарываешься?",
        "Почему у тебя отчество нюх?",
    )

    for sample in samples:
        assert v3._EXTRA_FIGHT_RE.search(sample), sample


def test_reconciliation_cancels_post_fight_logic():
    assert v3.is_reconciliation("Ну всё, обнял тогда")
    assert v3.is_reconciliation("Согласен, борщанул, без обид")
    assert not v3.is_reconciliation("Ну всё, ещё один раунд")


def test_bait_reveal_is_recognized():
    assert v3.is_bait_reveal("Да я тебя просто байтил")
    assert v3.is_bait_reveal("Фотка вообще двухнедельной давности")
    assert not v3.is_bait_reveal("Собака лапу порезала")


def test_sniff_theme_comes_from_observed_fight_text_only():
    assert v3.fight_theme(["Хуй будешь нюхать?", "нюхал хуй"]) == "sniff"
    assert v3.fight_theme(["ты опять споришь", "ну и что"]) == "generic"


def test_afterburner_uses_sniff_callback_when_target_went_silent(monkeypatch):
    monkeypatch.setattr(v3.random, "choice", lambda items: items[0])
    state = v3.AfterburnerState(
        chat_id=-100,
        user_id=77,
        username="funnyelephant",
        fight_texts=["Хуй будешь нюхать?", "нюхал хуй"],
    )

    line = v3._pick_afterburner_line(state)

    assert "@funnyelephant" in line
    assert "занюх" in line
    assert "слился" in line


def test_afterburner_notices_target_talking_to_others(monkeypatch):
    monkeypatch.setattr(v3.random, "choice", lambda items: items[0])
    state = v3.AfterburnerState(
        chat_id=-100,
        user_id=77,
        username="funnyelephant",
        target_spoke_after=True,
        fight_texts=["нюхать хуй"],
    )

    line = v3._pick_afterburner_line(state)

    assert "с остальными уже разговорчивый" in line
    assert "нюхательную диссертацию" in line


def test_normal_group_compaction_has_hard_character_bound():
    text = (
        "Первая длинная мысль про чат и его нравы. "
        "Вторая длинная мысль, которая продолжает ненужную лекцию. "
        "Третья длинная мысль с ещё одним выводом. "
        "Четвёртая длинная мысль. Пятая мысль, которую уже точно не просили."
    )

    compact = v3._compact_text(text, max_chars=120, max_sentences=2)

    assert len(compact) <= 120
    assert compact != text
