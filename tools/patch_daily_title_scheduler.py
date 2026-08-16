from pathlib import Path

BOT = Path("bot.py")
text = BOT.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 match, got {count}")
    text = text.replace(old, new, 1)


# 1) Persist whether the automatic title announcement actually reached Telegram.
replace_once(
    '''        # Расписание автоматического недельного отчёта.\n''',
    '''        # Отдельно отмечаем, что daily title уже реально объявлен в Telegram.\n        # Если отправка упадёт после атомарного выбора победителя, scheduler\n        # повторит только объявление, а не выберет второго человека.\n        _ensure_column(\n            connection,\n            "daily_title_assignments",\n            "announced_at",\n            "announced_at TEXT",\n        )\n\n        # Расписание автоматического недельного отчёта.\n''',
    "daily title announced_at migration",
)

# 2) get_chat_settings must expose the weekly fields that already live in SQLite.
replace_once(
    '''    "last_intervention_at": None,\n}\n''',
    '''    "last_intervention_at": None,\n    "weekly_report_enabled": False,\n    "weekly_report_weekday": 6,\n    "weekly_report_time": "21:00",\n    "weekly_report_last_sent_date": None,\n}\n''',
    "default weekly settings",
)

replace_once(
    '''                trigger_replies_count,\n                last_intervention_at\n            FROM chat_settings\n''',
    '''                trigger_replies_count,\n                last_intervention_at,\n                weekly_report_enabled,\n                weekly_report_weekday,\n                weekly_report_time,\n                weekly_report_last_sent_date\n            FROM chat_settings\n''',
    "weekly settings select",
)

replace_once(
    '''        "trigger_replies_count": int(row[6]),\n        "last_intervention_at": row[7],\n    }\n''',
    '''        "trigger_replies_count": int(row[6]),\n        "last_intervention_at": row[7],\n        "weekly_report_enabled": bool(row[8]),\n        "weekly_report_weekday": int(row[9]),\n        "weekly_report_time": str(row[10]),\n        "weekly_report_last_sent_date": row[11],\n    }\n''',
    "weekly settings mapping",
)

# 3) Daily assignment now exposes announcement state.
replace_once(
    '''            SELECT user_id, title, assigned_at\n            FROM daily_title_assignments\n''',
    '''            SELECT user_id, title, assigned_at, announced_at\n            FROM daily_title_assignments\n''',
    "daily assignment select",
)

replace_once(
    '''        "assigned_at": str(row[2]),\n    }\n\n\nasync def get_daily_title_assignment(\n''',
    '''        "assigned_at": str(row[2]),\n        "announced_at": (str(row[3]) if row[3] else None),\n    }\n\n\nasync def get_daily_title_assignment(\n''',
    "daily assignment mapping",
)

# 4) Daily title is no longer a Hard Mode side effect.
replace_once(
    '''    # V2 daily title — отдельное единичное вмешательство. Если оно\n    # сработало, не наслаиваем reaction/random reply на то же сообщение.\n    if await maybe_assign_daily_title(update):\n        return\n\n''',
    '''''',
    "remove hard-mode daily title trigger",
)

# 5) Status for weekly auto-report and convenient /week_time with no args.
week_status = r'''
async def week_auto_status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Показывает текущее расписание автоматического недельного отчёта."""

    del context

    if not update.message or not update.effective_chat:
        return

    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text(
            "Авто-отчёт существует только для групп."
        )
        return

    settings = await get_chat_settings(
        update.effective_chat.id,
        str(update.effective_chat.type),
    )

    enabled = bool(settings.get("weekly_report_enabled", False))
    weekday = int(settings.get("weekly_report_weekday", 6))
    report_time = str(settings.get("weekly_report_time", "21:00"))
    last_sent = settings.get("weekly_report_last_sent_date") or "ещё не отправлялся"

    await update.message.reply_text(
        "Автоматический недельный отчёт:\n"
        f"Статус: {'включён' if enabled else 'выключен'}\n"
        f"Расписание: {WEEKDAY_LABELS_RU.get(weekday, 'воскресенье')} "
        f"в {report_time} по МСК\n"
        f"Последняя успешная авто-отправка: {last_sent}"
    )


'''
replace_once(
    '''async def week_time_command(\n''',
    week_status + '''async def week_time_command(\n''',
    "insert weekly status command",
)

replace_once(
    '''    if not context.args or len(context.args) < 2:\n        await update.message.reply_text(\n            "Формат: /week_time воскресенье 21:00"\n        )\n        return\n''',
    '''    if not context.args:\n        await week_auto_status_command(update, context)\n        return\n\n    if len(context.args) < 2:\n        await update.message.reply_text(\n            "Формат: /week_time воскресенье 21:00"\n        )\n        return\n''',
    "week_time status shortcut",
)

# 6) Human-readable title status.
title_status = r'''
async def title_status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Показывает статус автоматического титула дня в этой группе."""

    del context

    if not update.message or not update.effective_chat:
        return

    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text(
            "Титул дня автоматически разыгрывается только в группах."
        )
        return

    now = current_msk_datetime()
    date = now.date().isoformat()
    assignment = await get_daily_title_assignment(
        update.effective_chat.id,
        date,
    )

    if assignment:
        profile = await get_member_profile(
            update.effective_chat.id,
            assignment["user_id"],
        )
        display_name = (
            profile.get("current_display_name")
            if profile
            else None
        ) or f"участник {assignment['user_id']}"
        announced = "да" if assignment.get("announced_at") else "ожидает отправки"
        await update.message.reply_text(
            "Титул дня:\n"
            f"Сегодня уже выбран: {display_name} — «{assignment['title']}»\n"
            f"Объявлен в чат: {announced}\n"
            "Новый титул заменяет предыдущий; одновременно у человека только один."
        )
        return

    activity = await get_weekly_activity(
        update.effective_chat.id,
        date,
        date,
    )
    known_members = await list_chat_member_profiles(
        update.effective_chat.id,
        limit=200,
    )
    candidates = daily_title_engine.build_candidates(
        activity,
        known_members,
    )

    window = (
        "уже открыто"
        if daily_title_engine.is_assignment_window_open(now)
        else f"откроется после {daily_title_engine.DAILY_TITLE_START_HOUR_MSK}:00 МСК"
    )
    await update.message.reply_text(
        "Титул дня:\n"
        "Статус: сегодня ещё не выбран\n"
        f"Окно выдачи: {window}\n"
        f"Активных кандидатов сегодня: {len(candidates)}\n"
        "Выбор равновероятный среди тех, кто сегодня писал в чат."
    )


'''
replace_once(
    '''# ============================================================\n# РАЗВЛЕКАТЕЛЬНЫЕ КОМАНДЫ: С GEMINI\n''',
    title_status + '''# ============================================================\n# РАЗВЛЕКАТЕЛЬНЫЕ КОМАНДЫ: С GEMINI\n''',
    "insert title status command",
)

# 7) Independent scheduler for daily titles.
daily_scheduler = r'''
# ============================================================
# АВТОМАТИЧЕСКИЙ ТИТУЛ ДНЯ
# ============================================================

DAILY_TITLE_CHECK_INTERVAL_SECONDS = 60


def get_daily_title_chat_ids_sync(date: str) -> list[int]:
    """Группы, где сегодня есть хотя бы один активный участник."""

    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT activity.chat_id
            FROM chat_activity_daily AS activity
            JOIN chats ON chats.chat_id = activity.chat_id
            WHERE activity.date = ?
              AND activity.messages > 0
              AND chats.chat_type IN ('group', 'supergroup')
            ORDER BY activity.chat_id
            """,
            (date,),
        ).fetchall()

    return [int(row[0]) for row in rows]


async def get_daily_title_chat_ids(date: str) -> list[int]:
    return await asyncio.to_thread(
        get_daily_title_chat_ids_sync,
        date,
    )


def mark_daily_title_announced_sync(chat_id: int, date: str) -> None:
    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE daily_title_assignments
            SET announced_at = datetime('now')
            WHERE chat_id = ? AND date = ?
            """,
            (chat_id, date),
        )
        connection.commit()


async def mark_daily_title_announced(chat_id: int, date: str) -> None:
    await asyncio.to_thread(
        mark_daily_title_announced_sync,
        chat_id,
        date,
    )


async def _daily_title_display_name(chat_id: int, user_id: int) -> str:
    profile = await get_member_profile(chat_id, user_id)
    if profile and profile.get("current_display_name"):
        return str(profile["current_display_name"])
    return f"участник {user_id}"


async def run_due_daily_titles(application: Application) -> None:
    """После 18:00 МСК выдаёт ровно один daily title каждой активной группе."""

    now = current_msk_datetime()
    if not daily_title_engine.is_assignment_window_open(now):
        return

    date = now.date().isoformat()

    for chat_id in await get_daily_title_chat_ids(date):
        assignment = await get_daily_title_assignment(chat_id, date)
        display_name: str | None = None

        if assignment and assignment.get("announced_at"):
            continue

        if assignment is None:
            activity = await get_weekly_activity(chat_id, date, date)
            known_members = await list_chat_member_profiles(chat_id, limit=200)
            candidates = daily_title_engine.build_candidates(
                activity,
                known_members,
            )
            candidate = daily_title_engine.choose_candidate(candidates)
            if candidate is None:
                continue

            new_title = pick_new_title(candidate.previous_title)
            created = await try_assign_daily_title(
                chat_id,
                date,
                candidate.user_id,
                new_title,
            )

            if created:
                assignment = {
                    "user_id": candidate.user_id,
                    "title": new_title,
                    "announced_at": None,
                }
                display_name = candidate.display_name
            else:
                assignment = await get_daily_title_assignment(chat_id, date)

        if not assignment or assignment.get("announced_at"):
            continue

        if display_name is None:
            display_name = await _daily_title_display_name(
                chat_id,
                int(assignment["user_id"]),
            )

        try:
            await application.bot.send_message(
                chat_id=chat_id,
                text=daily_title_engine.format_daily_title_message(
                    display_name,
                    str(assignment["title"]),
                ),
            )
        except Exception as error:
            logging.warning(
                "Не удалось объявить титул дня в чате %s: %s "
                "(повторим на следующей минуте)",
                chat_id,
                error,
            )
            continue

        await mark_daily_title_announced(chat_id, date)


async def daily_title_scheduler_loop(application: Application) -> None:
    """Фоновая задача: после 18:00 МСК проверяет daily titles раз в минуту."""

    while True:
        await asyncio.sleep(DAILY_TITLE_CHECK_INTERVAL_SECONDS)

        try:
            await run_due_daily_titles(application)
        except Exception as error:
            logging.warning(
                "Ошибка планировщика титула дня: %s",
                error,
            )


'''
replace_once(
    '''# ============================================================\n# АНТИСПАМ ДЛЯ СЛУЧАЙНЫХ ВМЕШАТЕЛЬСТВ В ГРУППЕ\n''',
    daily_scheduler + '''# ============================================================\n# АНТИСПАМ ДЛЯ СЛУЧАЙНЫХ ВМЕШАТЕЛЬСТВ В ГРУППЕ\n''',
    "insert daily title scheduler",
)

# 8) Start the new scheduler with the app.
replace_once(
    '''    application.create_task(\n        weekly_report_scheduler_loop(application),\n        name="weekly_report_scheduler",\n    )\n''',
    '''    application.create_task(\n        weekly_report_scheduler_loop(application),\n        name="weekly_report_scheduler",\n    )\n    application.create_task(\n        daily_title_scheduler_loop(application),\n        name="daily_title_scheduler",\n    )\n''',
    "start daily title scheduler",
)

# 9) Register diagnostic commands.
replace_once(
    '''        CommandHandler(\n            "title",\n            title_command,\n        )\n    )\n''',
    '''        CommandHandler(\n            "title",\n            title_command,\n        )\n    )\n    application.add_handler(\n        CommandHandler(\n            "title_status",\n            title_status_command,\n        )\n    )\n''',
    "register title status",
)

replace_once(
    '''        CommandHandler(\n            "week_auto_off",\n            week_auto_off_command,\n        )\n    )\n    application.add_handler(\n        CommandHandler(\n            "week_time",\n            week_time_command,\n        )\n    )\n''',
    '''        CommandHandler(\n            "week_auto_off",\n            week_auto_off_command,\n        )\n    )\n    application.add_handler(\n        CommandHandler(\n            "week_auto_status",\n            week_auto_status_command,\n        )\n    )\n    application.add_handler(\n        CommandHandler(\n            "week_time",\n            week_time_command,\n        )\n    )\n''',
    "register weekly status",
)

# 10) Help text should make the diagnostics discoverable.
replace_once(
    '''    "/awards — шуточные награды недели\\n"\n)\n''',
    '''    "/awards — шуточные награды недели\\n"\n    "/week_auto_status — статус автоматического недельного отчёта\\n"\n    "/title_status — статус автоматического титула дня\\n"\n)\n''',
    "help status commands",
)

BOT.write_text(text, encoding="utf-8")

# Regression tests are intentionally generated here so the patch and tests land together.
TEST = Path("tests/test_daily_title_scheduler.py")
TEST.write_text(r'''from datetime import datetime, timedelta, timezone

import pytest

import bot


MSK = timezone(timedelta(hours=3))


def _fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "daily-title.db"
    monkeypatch.setattr(bot, "STATS_DB_PATH", db_path)
    bot.initialize_stats_database()
    return db_path


def _seed_member(chat_id: int, user_id: int, name: str, date: str):
    with bot.get_db_connection() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO chats (chat_id, chat_type) VALUES (?, 'group')",
            (chat_id,),
        )
        connection.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO chat_member_profiles
                (chat_id, user_id, current_display_name)
            VALUES (?, ?, ?)
            """,
            (chat_id, user_id, name),
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO chat_activity_daily
                (chat_id, user_id, date, messages)
            VALUES (?, ?, ?, 1)
            """,
            (chat_id, user_id, date),
        )
        connection.commit()


def test_daily_title_replaces_previous_title(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    chat_id = -1001
    user_id = 42
    _seed_member(chat_id, user_id, "Петя", "2026-08-16")

    assert bot.try_assign_daily_title_sync(
        chat_id, "2026-08-16", user_id, "Первый титул"
    )
    assert bot.try_assign_daily_title_sync(
        chat_id, "2026-08-17", user_id, "Второй титул"
    )

    profile = bot.get_member_profile_sync(chat_id, user_id)
    assert profile is not None
    assert profile["current_title"] == "Второй титул"

    with bot.get_db_connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM daily_title_assignments WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()[0]
    assert count == 2  # история дней есть, но current_title у человека ровно один


class _FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, *, chat_id, text):
        self.messages.append((chat_id, text))


class _FakeApplication:
    def __init__(self):
        self.bot = _FakeBot()


@pytest.mark.asyncio
async def test_scheduler_assigns_even_when_hard_mode_is_off(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    chat_id = -2002
    user_id = 77
    date = "2026-08-16"
    _seed_member(chat_id, user_id, "Вася", date)

    bot.update_chat_setting_sync(chat_id, "hard_mode_enabled", False, "group")
    monkeypatch.setattr(
        bot,
        "current_msk_datetime",
        lambda: datetime(2026, 8, 16, 19, 5, tzinfo=MSK),
    )
    monkeypatch.setattr(bot, "pick_new_title", lambda previous: "Титул теста")

    app = _FakeApplication()
    await bot.run_due_daily_titles(app)

    assert len(app.bot.messages) == 1
    assert "Вася" in app.bot.messages[0][1]
    assignment = bot.get_daily_title_assignment_sync(chat_id, date)
    assert assignment is not None
    assert assignment["announced_at"] is not None
    profile = bot.get_member_profile_sync(chat_id, user_id)
    assert profile["current_title"] == "Титул теста"

    # Повторная минутная проверка не должна отправить второй титул.
    await bot.run_due_daily_titles(app)
    assert len(app.bot.messages) == 1


@pytest.mark.asyncio
async def test_failed_announcement_retries_same_winner(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    chat_id = -3003
    user_id = 88
    date = "2026-08-16"
    _seed_member(chat_id, user_id, "Коля", date)

    monkeypatch.setattr(
        bot,
        "current_msk_datetime",
        lambda: datetime(2026, 8, 16, 19, 10, tzinfo=MSK),
    )
    monkeypatch.setattr(bot, "pick_new_title", lambda previous: "Несменяемый победитель")

    class FlakyBot:
        def __init__(self):
            self.calls = 0
            self.messages = []

        async def send_message(self, *, chat_id, text):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("network")
            self.messages.append((chat_id, text))

    app = _FakeApplication()
    app.bot = FlakyBot()

    await bot.run_due_daily_titles(app)
    first = bot.get_daily_title_assignment_sync(chat_id, date)
    assert first is not None
    assert first["user_id"] == user_id
    assert first["announced_at"] is None

    await bot.run_due_daily_titles(app)
    second = bot.get_daily_title_assignment_sync(chat_id, date)
    assert second["user_id"] == first["user_id"]
    assert second["title"] == first["title"]
    assert second["announced_at"] is not None
    assert len(app.bot.messages) == 1


def test_chat_settings_expose_weekly_schedule(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    chat_id = -4004
    bot.update_chat_setting_sync(chat_id, "weekly_report_enabled", True, "group")
    bot.update_chat_setting_sync(chat_id, "weekly_report_weekday", 5, "group")
    bot.update_chat_setting_sync(chat_id, "weekly_report_time", "20:30", "group")

    settings = bot.get_chat_settings_sync(chat_id, "group")
    assert settings["weekly_report_enabled"] is True
    assert settings["weekly_report_weekday"] == 5
    assert settings["weekly_report_time"] == "20:30"
    assert "weekly_report_last_sent_date" in settings
''', encoding="utf-8")

print("daily title scheduler patch applied")
