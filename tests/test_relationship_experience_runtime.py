import random

from telegram.ext import Application, MessageHandler

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


def test_dossier_relationship_uses_same_relationship_first_band_as_tone():
    assert profile_v4._relationship_label_from_profile({}) == "Нейтральный"
    assert profile_v4._relationship_label_from_profile({"chat_level": 4}) == "Знакомый нейтрал"
    assert profile_v4._relationship_label_from_profile({"reputation_score": 19}) == "Доброжелательный"
    assert profile_v4._relationship_label_from_profile({"reputation_score": 40}) == "Очень свой"
    assert profile_v4._relationship_label_from_profile(
        {"reputation_score": -20, "chat_level": 3}
    ) == "Старый спорщик"
    assert profile_v4._relationship_label_from_profile(
        {"reputation_score": -20, "chat_level": 0}
    ) == "Настороженный"


def test_today_line_describes_only_current_day_climate():
    assert profile_v4._today_line(0, 0, 0, False) == "Спокойно"
    assert profile_v4._today_line(0, 2, 1, False) == "Помирились"
    assert profile_v4._today_line(1, 1, 0, False) == "Лёгкий конфликт — 1 наезд сегодня"
    assert profile_v4._today_line(3, 3, 0, False) == "Конфликтно — 3 наезда сегодня"
    assert "ритуал" in profile_v4._today_line(0, 2, 1, True)


def test_public_reputation_line_is_numeric_not_duplicate_relationship_label():
    assert profile_v4._reputation_score_line({"reputation_score": 19}) == "+19"
    assert profile_v4._reputation_score_line({"reputation_score": -7}) == "-7"


def test_dossier_sympathy_is_separate_from_chat_level():
    assert profile_v4._positive_line({}) == "Нейтральная"
    assert profile_v4._positive_line(
        {
            "chat_level": 4,
            "positive_affinity_points_30d": 4,
            "positive_streak": 2,
        }
    ) == "Доброжелательная"

    assert profile_v4._positive_line({"chat_level": 4}) == "Нейтральная"
    assert profile_v4._positive_line(
        {
            "chat_level": 0,
            "reputation_score": 19,
            "positive_affinity_points_30d": 0,
        }
    ) == "Доброжелательная"


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
    assert profile_v3._theme_ok("ответ") is False
    assert profile_v3._theme_ok("вроде") is False


def test_theme_ok_rejects_phrase_with_any_noise_word():
    assert profile_v3._theme_ok("тоже пройдено") is False
    assert profile_v3._theme_ok("игры сегодня") is False
    assert profile_v3._theme_ok("любимые игры") is True


def test_dynamic_verdict_is_one_short_line():
    verdict = dynamic_verdict._clean_verdict(
        "«Весь месяц спорит с реальностью, а реальность, сука, даже не подписывалась.»\nВторая строка"
    )
    assert verdict is not None
    assert "\n" not in verdict
    assert len(verdict) <= dynamic_verdict.MAX_VERDICT_CHARS
    assert not verdict.startswith("«")


def test_prepare_application_initializes_augments_and_registers_once(monkeypatch):
    fake_bot_module = object()
    calls = []
    monkeypatch.setattr(runtime, "_find_bot_module", lambda: fake_bot_module)
    monkeypatch.setattr(runtime, "_initialize_tables", lambda bot: calls.append(("init", bot)))
    monkeypatch.setattr(runtime, "_augment_profile_functions", lambda bot: calls.append(("augment", bot)))

    application = Application.builder().token("123456:TESTTOKEN").build()
    runtime._PREPARED_APPLICATION_IDS.discard(id(application))
    runtime._prepare_application(application)
    runtime._prepare_application(application)

    assert calls == [("init", fake_bot_module), ("augment", fake_bot_module)]
    handlers = application.handlers.get(7, ())
    assert len(handlers) == 1
    assert isinstance(handlers[0], MessageHandler)
    assert handlers[0].callback is runtime._observe_relationship
