import asyncio
import random
import sqlite3
from datetime import datetime
from types import SimpleNamespace

from telegram.ext import Application, MessageHandler

import reputation_daily_runtime as daily
import reputation_runtime as lifetime


def _db_bot(tmp_path):
    path = tmp_path / "daily_reputation.db"

    def get_db_connection():
        return sqlite3.connect(path)

    return SimpleNamespace(
        get_db_connection=get_db_connection,
        current_msk_datetime=lambda: datetime(2026, 8, 20, 12, 0, 0),
        build_full_system_instruction=lambda *args, **kwargs: "BASE",
        detect_conversation_mode=lambda text: "hostile" if "нахуй" in str(text) else "normal",
    )


def _init(bot):
    lifetime._initialize_table(bot)
    daily._initialize_table(bot)


def _update(text: str):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100, type="group"),
        effective_user=SimpleNamespace(id=20, is_bot=False),
        effective_message=SimpleNamespace(text=text, reply_to_message=None),
    )


def _context():
    return SimpleNamespace(
        bot=SimpleNamespace(id=999, username="yayceslav_bot"),
    )


def test_first_clean_active_day_gets_one_random_bonus(tmp_path):
    bot = _db_bot(tmp_path)
    _init(bot)

    bonus = daily._grant_normal_day_bonus_sync(
        bot,
        10,
        20,
        "2026-08-20",
        rng=random.Random(5),
    )
    assert 1 <= bonus <= 5
    assert lifetime._state_sync(bot, 10, 20)["score"] == bonus
    assert daily._daily_state_sync(bot, 10, 20, "2026-08-20") == {
        "normal_bonus": bonus,
        "bonus_active": 1,
        "negative_seen": 0,
    }

    # Ten more normal messages on the same day do not farm reputation.
    for _ in range(10):
        assert daily._grant_normal_day_bonus_sync(
            bot,
            10,
            20,
            "2026-08-20",
            rng=random.Random(99),
        ) == 0
    assert lifetime._state_sync(bot, 10, 20)["score"] == bonus


def test_next_clean_calendar_day_can_grow_again(tmp_path):
    bot = _db_bot(tmp_path)
    _init(bot)

    first = daily._grant_normal_day_bonus_sync(
        bot, 1, 2, "2026-08-20", rng=random.Random(1)
    )
    second = daily._grant_normal_day_bonus_sync(
        bot, 1, 2, "2026-08-21", rng=random.Random(2)
    )
    assert 1 <= first <= 5
    assert 1 <= second <= 5
    assert lifetime._state_sync(bot, 1, 2)["score"] == first + second


def test_same_day_hostility_revokes_passive_bonus_but_keeps_real_penalty(tmp_path):
    bot = _db_bot(tmp_path)
    _init(bot)

    bonus = daily._grant_normal_day_bonus_sync(
        bot, 1, 2, "2026-08-20", rng=SimpleNamespace(randint=lambda a, b: 5)
    )
    assert bonus == 5
    assert lifetime._state_sync(bot, 1, 2)["score"] == 5

    # group-10 explicit reputation runs first: "пошёл нахуй" = -9.
    lifetime._apply_delta_sync(bot, 1, 2, -9, "negative")
    assert lifetime._state_sync(bot, 1, 2)["score"] == -4

    # group-11 then invalidates the morning passive +5.
    revoked = daily._mark_negative_day_and_revoke_sync(bot, 1, 2, "2026-08-20")
    assert revoked == 5
    state = lifetime._state_sync(bot, 1, 2)
    assert state["score"] == -9
    # Revoking passive goodwill does not fake another explicit negative event.
    assert state["negative_points"] == 9
    assert state["negative_events"] == 1
    assert daily._daily_state_sync(bot, 1, 2, "2026-08-20") == {
        "normal_bonus": 5,
        "bonus_active": 0,
        "negative_seen": 1,
    }

    # Once the day became hostile, later normal messages cannot earn it back.
    assert daily._grant_normal_day_bonus_sync(
        bot, 1, 2, "2026-08-20", rng=random.Random(3)
    ) == 0


def test_hostility_as_first_message_blocks_daily_bonus(tmp_path):
    bot = _db_bot(tmp_path)
    _init(bot)

    assert daily._mark_negative_day_and_revoke_sync(bot, 1, 2, "2026-08-20") == 0
    assert daily._grant_normal_day_bonus_sync(
        bot, 1, 2, "2026-08-20", rng=random.Random(4)
    ) == 0
    assert lifetime._state_sync(bot, 1, 2)["score"] == 0


def test_background_normal_chat_earns_goodwill_without_addressing_bot(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    _init(bot)
    monkeypatch.setattr(daily, "_find_bot_module", lambda: bot)

    asyncio.run(daily._observe_daily_reputation(_update("всем привет, как дела"), _context()))
    score = int(lifetime._state_sync(bot, -100, 20)["score"])
    assert 1 <= score <= 5


def test_background_hostility_revokes_goodwill_without_explicit_bot_penalty(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    _init(bot)
    monkeypatch.setattr(daily, "_find_bot_module", lambda: bot)

    bonus = daily._grant_normal_day_bonus_sync(
        bot, -100, 20, "2026-08-20", rng=SimpleNamespace(randint=lambda a, b: 4)
    )
    assert bonus == 4

    # Not addressed to Yayceslav: no explicit -9 should be created, but this is
    # no longer a clean social day, so passive +4 is removed.
    asyncio.run(daily._observe_daily_reputation(_update("пошёл нахуй"), _context()))
    state = lifetime._state_sync(bot, -100, 20)
    assert state["score"] == 0
    assert state["negative_points"] == 0
    assert state["negative_events"] == 0
    assert daily._daily_state_sync(bot, -100, 20, "2026-08-20")["negative_seen"] == 1


def test_bonus_respects_plus_100_cap_and_revokes_only_actual_gain(tmp_path):
    bot = _db_bot(tmp_path)
    _init(bot)
    lifetime._apply_delta_sync(bot, 1, 2, 10, "positive")
    for _ in range(9):
        lifetime._apply_delta_sync(bot, 1, 2, 10, "positive")
    assert lifetime._state_sync(bot, 1, 2)["score"] == 100

    # At the cap there is no phantom bonus to revoke later.
    assert daily._grant_normal_day_bonus_sync(
        bot, 1, 2, "2026-08-20", rng=SimpleNamespace(randint=lambda a, b: 5)
    ) == 0
    assert daily._mark_negative_day_and_revoke_sync(bot, 1, 2, "2026-08-20") == 0
    assert lifetime._state_sync(bot, 1, 2)["score"] == 100


def test_small_positive_reputation_gets_goodwill_override(tmp_path):
    bot = _db_bot(tmp_path)
    _init(bot)
    daily._grant_normal_day_bonus_sync(
        bot, 1, 2, "2026-08-20", rng=SimpleNamespace(randint=lambda a, b: 3)
    )

    daily._patch_instruction(bot)
    result = bot.build_full_system_instruction("обычный вопрос", chat_id=1, user_id=2)
    assert "NATURAL GOODWILL OVERRIDE" in result
    assert "общается нормально" in result
    assert "не льсти" in result


def test_prepare_registers_group11_once(tmp_path, monkeypatch):
    bot = _db_bot(tmp_path)
    calls = []
    monkeypatch.setattr(daily, "_find_bot_module", lambda: bot)
    monkeypatch.setattr(daily, "_initialize_table", lambda value: calls.append("table"))
    monkeypatch.setattr(daily, "_patch_instruction", lambda value: calls.append("instruction"))

    application = Application.builder().token("123456:TESTTOKEN").build()
    daily._PREPARED_APPLICATION_IDS.discard(id(application))
    daily._prepare_application(application)
    daily._prepare_application(application)

    assert calls == ["table", "instruction"]
    handlers = application.handlers.get(11, ())
    assert len(handlers) == 1
    assert isinstance(handlers[0], MessageHandler)
    assert handlers[0].callback is daily._observe_daily_reputation
