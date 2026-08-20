import asyncio
import sqlite3
from datetime import datetime
from types import SimpleNamespace

import pytest

import initiative_runtime as initiative


def _db_bot(tmp_path, now=None, original_calls=None):
    path = tmp_path / "initiative.db"

    def get_db_connection():
        return sqlite3.connect(path)

    async def run_due_daily_titles(application):
        if original_calls is not None:
            original_calls.append(application)

    bot = SimpleNamespace(
        get_db_connection=get_db_connection,
        current_msk_datetime=lambda: now or datetime(2026, 8, 20, 15, 0, 0),
        run_due_daily_titles=run_due_daily_titles,
    )

    with bot.get_db_connection() as connection:
        connection.execute(
            "CREATE TABLE chats (chat_id INTEGER PRIMARY KEY, chat_type TEXT NOT NULL)"
        )
        connection.execute(
            """
            CREATE TABLE chat_activity_daily (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                messages INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.commit()
    return bot


def _seed_activity(bot, chat_id, date, messages, chat_type="group"):
    with bot.get_db_connection() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO chats (chat_id, chat_type) VALUES (?, ?)",
            (chat_id, chat_type),
        )
        connection.execute(
            "INSERT INTO chat_activity_daily (chat_id, user_id, date, messages) VALUES (?, ?, ?, ?)",
            (chat_id, 1, date, messages),
        )
        connection.commit()


def _seed_decision(bot, chat_id, date, *, will_fire, fire_at_hour, sent_at=None):
    with bot.get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO chat_initiative_log (chat_id, date, will_fire, fire_at_hour, sent_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chat_id, date, 1 if will_fire else 0, fire_at_hour, sent_at),
        )
        connection.commit()


class _FakeApplication:
    def __init__(self):
        self.sent = []
        self.bot = SimpleNamespace(send_message=self._send_message)

    async def _send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


def test_eligible_chats_require_message_threshold(tmp_path):
    bot = _db_bot(tmp_path)
    initiative._initialize_table(bot)
    _seed_activity(bot, -100, "2026-08-20", 3)  # below threshold
    _seed_activity(bot, -200, "2026-08-20", 8)  # exactly at threshold

    chat_ids = initiative._eligible_chat_ids_sync(bot, "2026-08-20")
    assert chat_ids == [-200]


def test_eligible_chats_ignore_private_chats(tmp_path):
    bot = _db_bot(tmp_path)
    initiative._initialize_table(bot)
    _seed_activity(bot, -300, "2026-08-20", 50, chat_type="private")

    assert initiative._eligible_chat_ids_sync(bot, "2026-08-20") == []


def test_decision_is_made_once_per_day(tmp_path):
    bot = _db_bot(tmp_path)
    initiative._initialize_table(bot)

    class AlwaysFire:
        def random(self):
            return 0.0

        def randint(self, a, b):
            return a

    first = initiative._ensure_today_decision_sync(bot, -100, "2026-08-20", rng=AlwaysFire())

    class NeverFire:
        def random(self):
            return 0.99

        def randint(self, a, b):
            return b

    second = initiative._ensure_today_decision_sync(bot, -100, "2026-08-20", rng=NeverFire())
    assert first == second  # the second call's rng never wins the INSERT OR IGNORE race


def test_ttl_sweep_removes_old_rows(tmp_path):
    bot = _db_bot(tmp_path)
    initiative._initialize_table(bot)
    _seed_decision(bot, -100, "2026-01-01", will_fire=False, fire_at_hour=15)

    initiative._ensure_today_decision_sync(bot, -100, "2026-08-20")
    with bot.get_db_connection() as connection:
        dates = [
            row[0]
            for row in connection.execute(
                "SELECT date FROM chat_initiative_log WHERE chat_id = -100 ORDER BY date"
            ).fetchall()
        ]
    assert dates == ["2026-08-20"]


def test_fire_probability_scales_with_miss_streak():
    assert initiative.fire_probability_for_streak(0) == pytest.approx(0.15)
    assert initiative.fire_probability_for_streak(1) == pytest.approx(0.30)
    assert initiative.fire_probability_for_streak(2) == pytest.approx(0.45)


def test_fire_probability_caps_at_one():
    assert initiative.fire_probability_for_streak(100) == 1.0


def test_a_miss_raises_next_days_probability(tmp_path):
    bot = _db_bot(tmp_path)
    initiative._initialize_table(bot)

    class NeverFireExactly30Percent:
        """Rolls just above 15% (misses day 1) but below 30% (fires day 2)."""

        def random(self):
            return 0.20

        def randint(self, a, b):
            return a

    day1 = initiative._ensure_today_decision_sync(
        bot, -100, "2026-08-20", rng=NeverFireExactly30Percent()
    )
    assert day1["will_fire"] is False
    assert initiative._current_miss_streak_sync(bot, -100) == 1

    day2 = initiative._ensure_today_decision_sync(
        bot, -100, "2026-08-21", rng=NeverFireExactly30Percent()
    )
    assert day2["will_fire"] is True  # 0.20 < 30% (streak-scaled), unlike day 1's 15%


def test_two_consecutive_misses_double_streak(tmp_path):
    bot = _db_bot(tmp_path)
    initiative._initialize_table(bot)

    class NeverRolls:
        def random(self):
            return 0.99

        def randint(self, a, b):
            return a

    initiative._ensure_today_decision_sync(bot, -100, "2026-08-20", rng=NeverRolls())
    initiative._ensure_today_decision_sync(bot, -100, "2026-08-21", rng=NeverRolls())
    assert initiative._current_miss_streak_sync(bot, -100) == 2


def test_successful_send_resets_streak(tmp_path):
    now = datetime(2026, 8, 20, 15, 0, 0)
    bot = _db_bot(tmp_path, now=now)
    initiative._initialize_table(bot)
    initiative._record_miss_sync(bot, -100)
    initiative._record_miss_sync(bot, -100)
    assert initiative._current_miss_streak_sync(bot, -100) == 2

    _seed_activity(bot, -100, "2026-08-20", 20)
    _seed_decision(bot, -100, "2026-08-20", will_fire=True, fire_at_hour=12)

    application = _FakeApplication()
    original_find = initiative._find_bot_module
    initiative._find_bot_module = lambda: bot
    try:
        asyncio.run(initiative._run_initiative(application))
    finally:
        initiative._find_bot_module = original_find

    assert len(application.sent) == 1
    assert initiative._current_miss_streak_sync(bot, -100) == 0


def test_mark_sent_only_lets_one_caller_win(tmp_path):
    bot = _db_bot(tmp_path)
    initiative._initialize_table(bot)
    _seed_decision(bot, -100, "2026-08-20", will_fire=True, fire_at_hour=12)

    assert initiative._mark_sent_sync(bot, -100, "2026-08-20") is True
    assert initiative._mark_sent_sync(bot, -100, "2026-08-20") is False


def test_run_initiative_sends_when_due(tmp_path):
    now = datetime(2026, 8, 20, 15, 0, 0)
    bot = _db_bot(tmp_path, now=now)
    initiative._initialize_table(bot)
    _seed_activity(bot, -100, "2026-08-20", 20)
    _seed_decision(bot, -100, "2026-08-20", will_fire=True, fire_at_hour=12)

    application = _FakeApplication()
    original_find = initiative._find_bot_module
    initiative._find_bot_module = lambda: bot
    try:
        asyncio.run(initiative._run_initiative(application))
    finally:
        initiative._find_bot_module = original_find

    assert len(application.sent) == 1
    assert application.sent[0][0] == -100


def test_run_initiative_skips_before_fire_hour(tmp_path):
    now = datetime(2026, 8, 20, 10, 0, 0)
    bot = _db_bot(tmp_path, now=now)
    initiative._initialize_table(bot)
    _seed_activity(bot, -100, "2026-08-20", 20)
    _seed_decision(bot, -100, "2026-08-20", will_fire=True, fire_at_hour=12)

    application = _FakeApplication()
    original_find = initiative._find_bot_module
    initiative._find_bot_module = lambda: bot
    try:
        asyncio.run(initiative._run_initiative(application))
    finally:
        initiative._find_bot_module = original_find

    assert application.sent == []


def test_run_initiative_skips_when_will_fire_is_false(tmp_path):
    now = datetime(2026, 8, 20, 15, 0, 0)
    bot = _db_bot(tmp_path, now=now)
    initiative._initialize_table(bot)
    _seed_activity(bot, -100, "2026-08-20", 20)
    _seed_decision(bot, -100, "2026-08-20", will_fire=False, fire_at_hour=12)

    application = _FakeApplication()
    original_find = initiative._find_bot_module
    initiative._find_bot_module = lambda: bot
    try:
        asyncio.run(initiative._run_initiative(application))
    finally:
        initiative._find_bot_module = original_find

    assert application.sent == []


def test_run_initiative_never_sends_twice_same_day(tmp_path):
    now = datetime(2026, 8, 20, 15, 0, 0)
    bot = _db_bot(tmp_path, now=now)
    initiative._initialize_table(bot)
    _seed_activity(bot, -100, "2026-08-20", 20)
    _seed_decision(bot, -100, "2026-08-20", will_fire=True, fire_at_hour=12)

    application = _FakeApplication()
    original_find = initiative._find_bot_module
    initiative._find_bot_module = lambda: bot
    try:
        asyncio.run(initiative._run_initiative(application))
        asyncio.run(initiative._run_initiative(application))
    finally:
        initiative._find_bot_module = original_find

    assert len(application.sent) == 1


def test_patch_scheduler_calls_original_before_initiative(tmp_path):
    now = datetime(2026, 8, 20, 15, 0, 0)
    original_calls = []
    bot = _db_bot(tmp_path, now=now, original_calls=original_calls)
    initiative._initialize_table(bot)
    _seed_activity(bot, -100, "2026-08-20", 20)
    _seed_decision(bot, -100, "2026-08-20", will_fire=True, fire_at_hour=12)

    application = _FakeApplication()
    original_find = initiative._find_bot_module
    initiative._find_bot_module = lambda: bot
    try:
        initiative._patch_scheduler(bot)
        asyncio.run(bot.run_due_daily_titles(application))
    finally:
        initiative._find_bot_module = original_find

    assert original_calls == [application]
    assert len(application.sent) == 1


def test_patch_scheduler_guards_against_double_patch(tmp_path):
    bot = _db_bot(tmp_path)
    initiative._patch_scheduler(bot)
    wrapped_once = bot.run_due_daily_titles
    initiative._patch_scheduler(bot)
    assert bot.run_due_daily_titles is wrapped_once
