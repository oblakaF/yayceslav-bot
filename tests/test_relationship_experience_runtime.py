import random

import relationship_experience_runtime as runtime
import social_engine
import whoami_dynamic_verdict as dynamic_verdict
import whoami_profile_v3_runtime as profile_v3
import whoami_profile_v4_runtime as profile_v4


def test_monthly_chat_levels():
    assert runtime.chat_level_from_monthly_messages(0) == 0
    assert runtime.chat_level_from_monthly_messages(39) == 0
    assert runtime.chat_level_from_monthly_messages(40) == 1
    assert runtime.chat_level_from_monthly_messages(149) == 1
    assert runtime.chat_level_from_monthly_messages(150) == 2
    assert runtime.chat_level_from_monthly_messages(349) == 2
    assert runtime.chat_level_from_monthly_messages(350) == 3
    assert runtime.chat_level_from_monthly_messages(554) == 3
    assert runtime.chat_level_from_monthly_messages(555) == 3
    assert runtime.chat_level_from_monthly_messages(555, is_month_leader=True) == 4
    assert runtime.chat_level_from_monthly_messages(1200, is_month_leader=False) == 3
    assert runtime.chat_level_from_monthly_messages(1200, is_month_leader=True) == 4


def test_hostility_labels():
    assert runtime.hostility_label(0) == "Не хейтер"
    assert runtime.hostility_label(1) == "Мини-хейтер"
    assert runtime.hostility_label(2) == "Мини-хейтер"
    assert runtime.hostility_label(3) == "Мега-хейтер"
    assert runtime.hostility_label(10) == "Мега-хейтер"
    assert runtime.hostility_label(11) == "Гига-хейтер"


def test_dossier_relationship_labels_are_clear():
    assert profile_v4._relationship_label(0, 0) == "Незнакомец"
    assert profile_v4._relationship_label(1, 0) == "Знакомый"
    assert profile_v4._relationship_label(2, 0) == "Кореш"
    assert profile_v4._relationship_label(3, 0) == "Свой"
    assert profile_v4._relationship_label(4, 0) == "Любимчик"
    assert profile_v4._relationship_label(4, 1) == "Мини-хейтер"
    assert profile_v4._relationship_label(4, 3) == "Мега-хейтер"
    assert profile_v4._relationship_label(4, 11) == "Гига-хейтер"


def test_level_zero_non_hater_is_gentler():
    ctx = social_engine.SocialContext(
        chat_level=0,
        messages_month=20,
        friendliness_label="Не хейтер",
    )
    text = social_engine.build_social_instruction(ctx, rng=random.Random(1))
    assert "Не еби его слишком жёстко" in text


def test_low_level_hater_gets_angry_yaiceslav():
    ctx = social_engine.SocialContext(
        chat_level=0,
        messages_month=20,
        hostility_today=1,
        friendliness_label="Мини-хейтер",
    )
    text = social_engine.build_social_instruction(ctx, rng=random.Random(5))
    assert "отвечай зло" in text
    assert "Тепло выключено" in text


def test_non_hater_level_one_is_warm():
    ctx = social_engine.SocialContext(
        chat_level=1,
        messages_month=80,
        friendliness_label="Не хейтер",
    )
    text = social_engine.build_social_instruction(ctx, rng=random.Random(1))
    assert "добрее и теплее" in text


def test_penance_pending_can_offer_one_message_ritual():
    class AlwaysZero:
        @staticmethod
        def random():
            return 0.0

        @staticmethod
        def choice(values):
            return values[1] if len(values) > 1 else values[0]

    ctx = social_engine.SocialContext(
        chat_level=2,
        messages_month=250,
        hostility_today=2,
        friendliness_label="Мини-хейтер",
        forgiveness_count_today=1,
        relapse_count_today=1,
        penance_pending=True,
    )
    text = social_engine.build_social_instruction(ctx, rng=AlwaysZero())
    assert "дон-режим" in text or "200 виртуальных извинений" in text
    assert "одним сообщением" in text.lower()


def test_penance_phrases_are_lightweight():
    assert runtime._PENANCE_RE.search("Яйцеслав был прав, дон")
    assert runtime._PENANCE_RE.search("200 виртуальных извинений, дон")
    assert runtime._PENANCE_RE.search("мир, дон")


def test_theme_noise_is_filtered_but_milfs_survive():
    assert profile_v3._theme_ok("милфы") is True
    assert profile_v3._theme_ok("моду") is False
    assert profile_v3._theme_ok("одобряет") is False


def test_dynamic_verdict_is_one_short_line():
    verdict = dynamic_verdict._clean_verdict(
        "«Весь месяц спорит с реальностью, а реальность, сука, даже не подписывалась.»\nВторая строка"
    )
    assert verdict is not None
    assert "\n" not in verdict
    assert len(verdict) <= dynamic_verdict.MAX_VERDICT_CHARS
    assert not verdict.startswith("«")
