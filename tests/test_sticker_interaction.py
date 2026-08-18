import random

import sticker_engine
import sticker_interaction
import sticker_post_runtime


def test_question_sticker_probability_is_exactly_five_percent():
    assert sticker_interaction.QUESTION_STICKER_REPLY_CHANCE == 0.05


def test_own_sticker_visual_reply_probability_is_exactly_half():
    assert sticker_interaction.OWN_STICKER_REPLY_CHANCE == 0.50


def test_post_answer_tag_probability_is_exactly_five_percent():
    assert sticker_post_runtime.POST_TEXT_TAG_CHANCE == 0.05


def test_question_detector_handles_question_marks_and_russian_question_forms():
    assert sticker_interaction.is_question("Яйцеслав, ты вообще живой?")
    assert sticker_interaction.is_question("почему не работает")
    assert sticker_interaction.is_question("скажи что думаешь")
    assert not sticker_interaction.is_question("просто утверждение")


def test_own_pack_maps_cover_every_published_sticker():
    known = set(sticker_engine.STICKER_ORDER)
    assert set(sticker_interaction.OWN_STICKER_COMEBACKS) == known
    assert set(sticker_interaction.OWN_STICKER_TEXT_REPLIES) == known


def test_all_visual_comebacks_stay_inside_yayceslav_pack():
    known = set(sticker_engine.STICKER_ORDER)
    for incoming, replies in sticker_interaction.OWN_STICKER_COMEBACKS.items():
        assert incoming in known
        assert set(replies) <= known


def test_every_own_sticker_has_text_fallback():
    for key in sticker_engine.STICKER_ORDER:
        assert sticker_interaction.choose_own_pack_text_reply(
            key, rng=random.Random(1)
        ) in set(sticker_interaction.OWN_STICKER_TEXT_REPLIES[key])


def test_skill_issue_gets_a_real_visual_comeback():
    reply = sticker_interaction.choose_own_pack_comeback(
        "skill_issue",
        rng=random.Random(7),
    )
    assert reply in {"obtekay", "slabyy_zahod"}


def test_po_delu_govori_does_not_force_an_illogical_sticker_reply():
    assert sticker_interaction.choose_own_pack_comeback(
        "po_delu_govori",
        rng=random.Random(1),
    ) is None
    assert sticker_interaction.choose_own_pack_text_reply(
        "po_delu_govori",
        rng=random.Random(1),
    )


def test_minus_aura_counters_with_plus_aura():
    assert sticker_interaction.choose_own_pack_comeback(
        "minus_aura",
        rng=random.Random(1),
    ) == "plus_aura"


def test_pereigral_never_answers_za_dvizh():
    assert "za_dvizh" not in sticker_interaction.OWN_STICKER_COMEBACKS[
        "pereigral_i_unichtozhil"
    ]


def test_idi_nahui_has_only_banter_counter_stickers():
    assert set(sticker_interaction.OWN_STICKER_COMEBACKS["idi_nahui"]) == {
        "ne_bazar",
        "obtekay",
        "zavali_varezhku",
    }


def test_unknown_or_foreign_sticker_key_has_no_comeback_or_text():
    assert sticker_interaction.choose_own_pack_comeback("foreign_pack_sticker") is None
    assert sticker_interaction.choose_own_pack_text_reply("foreign_pack_sticker") is None


def test_semantic_question_prefers_matching_sticker_event():
    assert sticker_interaction.choose_question_sticker(
        "где пруфы на это?",
        rng=random.Random(1),
    ) == "gde_prufy"


def test_generic_question_has_no_random_sticker_candidate():
    assert sticker_interaction.choose_question_sticker(
        "как тебе погода сегодня?",
        rng=random.Random(3),
    ) is None


def test_waiting_question_can_use_waiting_stickers_only():
    result = sticker_interaction.choose_question_sticker(
        "сколько можно ждать уже?",
        rng=random.Random(3),
    )
    assert result in {"14_minut_blyat", "tyazhelo_tyazhelo"}


def test_direct_question_pool_never_contains_hard_hostile_stickers():
    outputs = {
        key
        for replies in sticker_interaction.QUESTION_EVENT_STICKERS.values()
        for key in replies
    }
    assert "idi_nahui" not in outputs
    assert "vremya_zavalit_ebalo" not in outputs


def test_old_idi_lesom_key_is_gone_everywhere():
    assert "idi_lesom" not in sticker_engine.STICKER_ORDER
    assert "idi_lesom" not in sticker_interaction.OWN_STICKER_COMEBACKS


def test_outplay_text_can_get_pereigral_as_second_message_tag():
    tag = sticker_post_runtime.choose_post_text_tag(
        "Ну всё, я тебя переиграл?",
        "Нет. Ты сам себе противоречишь, потому что в первом сообщении утверждал обратное.",
    )
    assert tag == "pereigral_i_unichtozhil"


def test_obvious_explanation_can_get_baza_as_second_message_tag():
    tag = sticker_post_runtime.choose_post_text_tag(
        "То есть это правда?",
        "Да, всё просто: в твоём примере условие уже выполнено.",
    )
    assert tag == "baza"


def test_post_answer_tag_does_not_fire_on_generic_statement():
    assert sticker_post_runtime.choose_post_text_tag(
        "Сегодня дождь.",
        "Да, похоже на дождливый день.",
    ) is None
