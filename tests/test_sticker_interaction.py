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


def test_unknown_or_foreign_sticker_key_has_no_comeback():
    assert sticker_interaction.choose_own_pack_comeback("foreign_pack_sticker") is None


def test_semantic_question_prefers_matching_sticker_event():
    assert sticker_interaction.choose_question_sticker(
        "где пруфы на это?",
        rng=random.Random(1),
    ) == "gde_prufy"


def test_generic_question_uses_only_generic_question_pool():
    result = sticker_interaction.choose_question_sticker(
        "как тебе погода сегодня?",
        rng=random.Random(3),
    )
    assert result in sticker_interaction.QUESTION_REPLY_STICKERS
