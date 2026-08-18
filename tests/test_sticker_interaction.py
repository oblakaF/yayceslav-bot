import random

import sticker_engine
import sticker_interaction


def test_question_sticker_probability_is_exactly_five_percent():
    assert sticker_interaction.QUESTION_STICKER_REPLY_CHANCE == 0.05


def test_question_detector_handles_question_marks_and_russian_question_forms():
    assert sticker_interaction.is_question("Яйцеслав, ты вообще живой?")
    assert sticker_interaction.is_question("почему не работает")
    assert sticker_interaction.is_question("скажи что думаешь")
    assert not sticker_interaction.is_question("просто утверждение")


def test_own_pack_comeback_map_covers_every_published_sticker():
    assert set(sticker_interaction.OWN_STICKER_COMEBACKS) == set(
        sticker_engine.STICKER_ORDER
    )


def test_all_own_pack_comebacks_stay_inside_yayceslav_pack():
    known = set(sticker_engine.STICKER_ORDER)
    for incoming, replies in sticker_interaction.OWN_STICKER_COMEBACKS.items():
        assert incoming in known
        assert replies
        assert set(replies) <= known


def test_skill_issue_gets_a_real_comeback_from_own_pack():
    reply = sticker_interaction.choose_own_pack_comeback(
        "skill_issue",
        rng=random.Random(7),
    )
    assert reply in {"obtekay", "slabyy_zahod", "zavali_varezhku"}


def test_new_stickers_have_semantic_comebacks():
    for key in sticker_engine.STICKER_ORDER[:9]:
        assert sticker_interaction.choose_own_pack_comeback(
            key, rng=random.Random(1)
        ) in set(sticker_interaction.OWN_STICKER_COMEBACKS[key])


def test_unknown_or_foreign_sticker_key_has_no_comeback():
    assert sticker_interaction.choose_own_pack_comeback("foreign_pack_sticker") is None


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
