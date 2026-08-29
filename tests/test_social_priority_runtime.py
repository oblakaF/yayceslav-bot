from types import SimpleNamespace

import runtime_bootstrap
import social_priority_runtime as runtime


def test_neutral_person_starts_restrained_and_non_hostile():
    snapshot = runtime.snapshot_from_profile(
        {
            "reputation_score": 0,
            "positive_affinity_level": 0,
            "relationship_level": 0,
        }
    )
    assert runtime.resolve_relationship_band(snapshot) == "neutral"
    instruction = runtime.build_priority_instruction(snapshot)
    assert "нейтрально-позитивно" in instruction
    assert "Никакой упреждающей токсичности" in instruction
    assert "Мат допустим" in instruction


def test_positive_affinity_is_primary_even_with_neutral_lifetime_score():
    snapshot = runtime.snapshot_from_profile(
        {
            "reputation_score": 0,
            "positive_affinity_level": 2,
            "positive_streak": 4,
            "relationship_level": 1,
        }
    )
    assert runtime.resolve_relationship_band(snapshot) == "friendly"
    instruction = runtime.build_priority_instruction(snapshot)
    assert "Яйцеслав к человеку расположен" in instruction
    assert "сочувствуй бытовым проблемам" in instruction


def test_real_feud_history_allows_playful_preemptive_banter_without_escalation():
    snapshot = runtime.snapshot_from_profile(
        {
            "reputation_score": -22,
            "relationship_level": 3,
            "chat_level": 3,
            "insults_to_bot": 8,
            "reputation_negative_events": 4,
            "replies_to_bot": 20,
        }
    )
    assert runtime.resolve_relationship_band(snapshot) == "feuding_familiar"
    instruction = runtime.build_priority_instruction(snapshot)
    assert "один короткий игровой упреждающий подкол" in instruction
    assert "Не считай каждую его реплику атакой" in instruction
    assert "не эскалируй первым" in instruction


def test_one_mild_bad_interaction_does_not_invent_a_recurring_feud():
    snapshot = runtime.snapshot_from_profile(
        {
            "reputation_score": -1,
            "hostility_today": 1,
            "relationship_level": 3,
            "reputation_negative_events": 1,
            "insults_to_bot": 1,
        }
    )
    assert snapshot.has_repeated_conflict_history is False
    assert runtime.resolve_relationship_band(snapshot) == "neutral_familiar"


def test_recurring_feud_history_is_not_erased_by_generic_positive_affinity():
    snapshot = runtime.snapshot_from_profile(
        {
            "reputation_score": 40,
            "positive_affinity_level": 4,
            "relationship_level": 3,
            "reputation_negative_events": 3,
            "insults_to_bot": 6,
        }
    )
    assert runtime.resolve_relationship_band(snapshot) == "feuding_familiar"


def test_negative_unfamiliar_person_is_wary_not_preemptively_abused():
    snapshot = runtime.snapshot_from_profile(
        {
            "reputation_score": -30,
            "relationship_level": 0,
            "chat_level": 0,
            "replies_to_bot": 1,
        }
    )
    assert runtime.resolve_relationship_band(snapshot) == "wary"
    instruction = runtime.build_priority_instruction(snapshot)
    assert "не начинай травлю" in instruction
    assert "близкой игровой динамики ещё нет" in instruction


def test_serious_context_overrides_even_established_feud():
    snapshot = runtime.snapshot_from_profile(
        {
            "reputation_score": -60,
            "relationship_level": 4,
            "insults_to_bot": 20,
        }
    )
    instruction = runtime.build_priority_instruction(
        snapshot,
        current_mode="serious",
        serious_topic=True,
    )
    assert "безопасность, точность и поддержка выше" in instruction
    assert "Не подкалывай и не припоминай конфликт" in instruction


def test_proactive_circle_keeps_twenty_percent_gate_and_content_first_tone():
    snapshot = runtime.snapshot_from_profile({"reputation_score": 0})
    instruction = runtime.build_priority_instruction(
        snapshot,
        media_kind="proactive_video",
        current_mode="media_unknown",
    )
    assert "20%-й шлюз реакции уже пройден" in instruction
    assert "НЕ меняет вероятность" in instruction
    assert "реплику по реальному содержанию кружка" in instruction
    assert "отдых" in instruction
    assert "пробки" in instruction
    assert "Не оскорбляй внешность" in instruction
    assert "горе, опасность" in instruction
    assert "Жалоба на пробки" in instruction


def test_voice_media_uses_actual_audio_not_service_prompt_as_user_tone():
    snapshot = runtime.snapshot_from_profile({"reputation_score": 0})
    instruction = runtime.build_priority_instruction(
        snapshot,
        media_kind="voice_or_audio",
        current_mode="media_unknown",
    )
    assert "служебный prompt обработки не является словами человека" in instruction
    assert "реальный контекст из медиа" in instruction
    assert "не сбрасывает отношения" in instruction
    assert "серьёзность сразу побеждает бантер" in instruction


def test_install_sanitizes_proactive_media_and_does_not_count_it_as_bot_call():
    calls = []

    def base(*args, **kwargs):
        calls.append((args, kwargs))
        return "BASE"

    module = SimpleNamespace(
        build_full_system_instruction=base,
        detect_conversation_mode=lambda text: "normal",
        is_serious_text=lambda text: False,
    )
    assert runtime.install(module) is True

    prompt = (
        "Тебя никто не звал и не спрашивал — ты сам решил вклиниться "
        "в чужой разговор. Посмотри видео-кружок и вставь мнение."
    )
    result = module.build_full_system_instruction(
        prompt,
        chat_type="group",
        bot_was_mentioned=True,
        member_profile={"reputation_score": 0},
    )

    recorded_args, recorded_kwargs = calls[-1]
    assert "служебное описание обработки" in recorded_args[0].lower()
    assert recorded_kwargs["bot_was_mentioned"] is False
    assert "RELATIONSHIP PRIORITY" in result


def test_install_handles_positional_media_context_without_duplicate_keywords():
    calls = []

    def base(*args, **kwargs):
        calls.append((args, kwargs))
        return "BASE"

    module = SimpleNamespace(
        build_full_system_instruction=base,
        detect_conversation_mode=lambda text: "normal",
        is_serious_text=lambda text: False,
    )
    assert runtime.install(module) is True

    prompt = (
        "Тебя никто не звал — ты сам решил вклиниться. "
        "Посмотри видео-кружок."
    )
    result = module.build_full_system_instruction(
        prompt,
        None,
        False,
        10,
        "group",
        "",
        None,
        True,
        {"reputation_score": -20, "relationship_level": 3},
        20,
    )

    recorded_args, recorded_kwargs = calls[-1]
    assert recorded_args[7] is False
    assert "служебное описание обработки" in recorded_args[0].lower()
    assert recorded_kwargs == {}
    assert "feuding_familiar" in result


def test_private_chat_is_not_given_group_relationship_policy():
    module = SimpleNamespace(
        build_full_system_instruction=lambda *args, **kwargs: "BASE",
        detect_conversation_mode=lambda text: "normal",
        is_serious_text=lambda text: False,
    )
    assert runtime.install(module) is True
    result = module.build_full_system_instruction(
        "обычный вопрос",
        chat_type="private",
        member_profile={"reputation_score": -90},
    )
    assert result == "BASE"


def test_bootstrap_installs_social_priority_after_date_and_before_voice2():
    order = runtime_bootstrap.RUNTIME_LOAD_ORDER
    assert "social_priority_runtime" in order
    assert order.index("date_grounding_runtime") < order.index("social_priority_runtime")
    assert order.index("social_priority_runtime") < order.index("voice2_runtime")
