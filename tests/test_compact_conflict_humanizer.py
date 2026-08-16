import random

import feedback_engine
import humanizer_engine
import hostile_streak_engine
import style_engine


def _trace(mode):
    return feedback_engine.ResponseTrace(
        chat_id=1, chat_type="group", conversation_mode=mode, message_intent="small_talk"
    )


def test_first_hostile_turn_is_physically_compacted_after_generation():
    text = (
        "Слышь, лопух, ты зеркало с чатом перепутал? "
        "Ты с батей-то посдержаннее общайся. "
        "А теперь начинается длинная ненужная лекция про аргументацию и контекст."
    )
    plan = humanizer_engine.humanize_reply(
        text, user_text="еблан", trace=_trace("hostile"), hostile_streak=1, rng=random.Random(9)
    )
    joined = " ".join(plan.messages)
    assert "лекция" not in joined
    assert len(joined) <= 125
    assert len(plan.messages) in {1, 2}


def test_short_direct_sendoff_stays_short():
    plan = humanizer_engine.humanize_reply(
        "Иди нахуй. Сейчас я тебе ещё объясню почему ты неправ.",
        user_text="пошел нахуй", trace=_trace("hostile"), hostile_streak=1, rng=random.Random(4)
    )
    assert "объясню" not in " ".join(plan.messages)
    assert len(" ".join(plan.messages)) <= 125


def test_third_hostile_turn_is_still_compact():
    text = "Первое предложение. Второе предложение. Третье предложение — это уже сознательный разнос."
    plan = humanizer_engine.humanize_reply(
        text, user_text="пошел нахуй", trace=_trace("hostile"), hostile_streak=3, rng=random.Random(2)
    )
    joined = " ".join(plan.messages)
    assert "Третье предложение" not in joined
    assert len(joined) <= 125


def test_psina_banter_is_compacted_even_if_mode_was_normal():
    text = (
        "Главный свидетель происходящего на связи, да. "
        "Мечтать не вредно, родной. "
        "Экспертная комиссия сейчас начнёт длинный монолог."
    )
    plan = humanizer_engine.humanize_reply(
        text,
        user_text="псина еще с нами, она стала умнее, но жить ему не долго )",
        trace=_trace("normal"),
        hostile_streak=0,
        rng=random.Random(7),
    )
    joined = " ".join(plan.messages)
    assert "Экспертная комиссия" not in joined
    assert len(joined) <= 125


def test_expanded_strong_insults_are_detected():
    samples = (
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
    )
    for sample in samples:
        assert humanizer_engine._looks_like_conflict(sample), sample


def test_ambiguous_insults_require_directed_context():
    directed = (
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
    for sample in directed:
        assert humanizer_engine._looks_like_conflict(sample), sample


def test_ambiguous_words_do_not_trigger_on_ordinary_sentences():
    ordinary = (
        "у меня собака заболела",
        "в цирке выступает клоун",
        "на ферме живёт баран",
        "крыса пробежала по подвалу",
        "свинья весит сто килограммов",
        "козёл стоит у забора",
    )
    for sample in ordinary:
        assert not humanizer_engine._looks_like_conflict(sample), sample


def test_directed_ambiguous_insult_is_physically_compacted():
    text = (
        "Ну наконец-то ты сформулировал мысль. "
        "Но сейчас я почему-то решил написать ещё три предложения. "
        "Вот эта часть уже должна исчезнуть."
    )
    plan = humanizer_engine.humanize_reply(
        text,
        user_text="ты клоун",
        trace=_trace("normal"),
        hostile_streak=0,
        rng=random.Random(8),
    )
    joined = " ".join(plan.messages)
    assert len(joined) <= 125
    assert "должна исчезнуть" not in joined


def test_challenge_is_also_compact_even_if_classifier_does_not_call_it_hostile():
    text = "О, уровень аргументации вырос до небес. Ты прямо гений контекста. А теперь длинный второй абзац."
    plan = humanizer_engine.humanize_reply(
        text, user_text="а ты гений простыней", trace=_trace("challenge"), rng=random.Random(3)
    )
    assert len(" ".join(plan.messages)) <= 155
    assert "длинный второй абзац" not in " ".join(plan.messages)


def test_old_russian_weight_is_reduced_but_forced_rus_remains_forced():
    assert style_engine._VOICE_PACK_WEIGHTS_BY_MODE["normal"][style_engine.VOICE_PACK_OLD_RUSSIAN] == 0.045
    assert style_engine._VOICE_PACK_WEIGHTS_BY_MODE["hostile"][style_engine.VOICE_PACK_OLD_RUSSIAN] == 0.030
    assert style_engine.choose_voice_pack(
        style_engine.VoicePackContext(selected_character="rus"), rng=random.Random(1)
    ) == style_engine.VOICE_PACK_OLD_RUSSIAN


def test_hostile_streak_current_observes_window():
    hostile_streak_engine.reset()
    assert hostile_streak_engine.observe(5, 6, hostile=True, now=100.0) == 1
    assert hostile_streak_engine.current(5, 6, now=101.0) == 1
    assert hostile_streak_engine.current(5, 6, now=1000.0) == 0


def test_voice_mix_rebalances_away_from_youth_and_skoof():
    normal = style_engine._VOICE_PACK_WEIGHTS_BY_MODE["normal"]
    assert normal[style_engine.VOICE_PACK_YOUTH] == 0.19
    assert normal[style_engine.VOICE_PACK_SKOOF] == 0.15
    assert normal[style_engine.VOICE_PACK_BLAT] == 0.13
    assert normal[style_engine.VOICE_PACK_POST_IRONY] == 0.09

    hostile = style_engine._VOICE_PACK_WEIGHTS_BY_MODE["hostile"]
    assert hostile[style_engine.VOICE_PACK_YOUTH] == 0.15
    assert hostile[style_engine.VOICE_PACK_SKOOF] == 0.12
    assert hostile[style_engine.VOICE_PACK_BLAT] == 0.31
    assert hostile[style_engine.VOICE_PACK_POST_IRONY] == 0.12
