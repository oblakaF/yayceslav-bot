import random

import relationship_experience_runtime as runtime
import social_engine
import whoami_profile_v3_runtime as profile_v3


def test_monthly_chat_levels():
    assert runtime.chat_level_from_monthly_messages(0) == 0
    assert runtime.chat_level_from_monthly_messages(99) == 0
    assert runtime.chat_level_from_monthly_messages(100) == 1
    assert runtime.chat_level_from_monthly_messages(299) == 1
    assert runtime.chat_level_from_monthly_messages(300) == 2
    assert runtime.chat_level_from_monthly_messages(499) == 2
    assert runtime.chat_level_from_monthly_messages(500) == 3
    assert runtime.chat_level_from_monthly_messages(999) == 3
    assert runtime.chat_level_from_monthly_messages(1000) == 4


def test_hostility_labels():
    assert runtime.hostility_label(0) == "Не хейтер"
    assert runtime.hostility_label(1) == "Мини-хейтер"
    assert runtime.hostility_label(2) == "Мини-хейтер"
    assert runtime.hostility_label(3) == "Мега-хейтер"
    assert runtime.hostility_label(10) == "Мега-хейтер"
    assert runtime.hostility_label(11) == "Гига-хейтер"


def test_level_zero_is_gentler():
    ctx = social_engine.SocialContext(
        chat_level=0,
        messages_30d=20,
        friendliness_label="Не хейтер",
    )
    text = social_engine.build_social_instruction(ctx, rng=random.Random(1))
    assert "Не еби его слишком жёстко" in text


def test_non_hater_level_one_is_warm():
    ctx = social_engine.SocialContext(
        chat_level=1,
        messages_30d=150,
        friendliness_label="Не хейтер",
    )
    text = social_engine.build_social_instruction(ctx, rng=random.Random(1))
    assert "добрее и теплее" in text


def test_giga_hater_requires_apology_until_reset():
    ctx = social_engine.SocialContext(
        chat_level=2,
        messages_30d=350,
        hostility_today=11,
        friendliness_label="Гига-хейтер",
    )
    text = social_engine.build_social_instruction(ctx, rng=random.Random(1))
    assert "до нормального извинения" in text
    assert "потребовать извиниться" in text


def test_theme_noise_is_filtered_but_milfs_survive():
    assert profile_v3._theme_ok("милфы") is True
    assert profile_v3._theme_ok("моду") is False
    assert profile_v3._theme_ok("одобряет") is False


def test_milf_verdict_is_short_and_thematic():
    verdict = profile_v3.topical_verdict(["милфы"], rng=random.Random(0))
    assert "милф" in verdict.lower()
    assert len(verdict) < 100
