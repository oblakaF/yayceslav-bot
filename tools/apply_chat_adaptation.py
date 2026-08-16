from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"marker not found: {label}")
    return text.replace(old, new, 1)


# ---------------- style_engine.py ----------------
path = Path("style_engine.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    'VOICE_PACK_RUNET_CLASSIC = "runet_classic"\n\nVOICE_PACKS = (',
    'VOICE_PACK_RUNET_CLASSIC = "runet_classic"\nVOICE_PACK_CHAT_NATIVE = "chat_native"\n\nVOICE_PACKS = (',
    "style constant",
)
text = replace_once(
    text,
    '    VOICE_PACK_RUNET_CLASSIC,\n)',
    '    VOICE_PACK_RUNET_CLASSIC,\n    VOICE_PACK_CHAT_NATIVE,\n)',
    "style tuple",
)
text = replace_once(
    text,
    'def choose_voice_pack(\n    ctx: VoicePackContext,\n    *,\n    rng=random,\n) -> str:',
    'def choose_voice_pack(\n    ctx: VoicePackContext,\n    *,\n    rng=random,\n    chat_native_weight: float = 0.0,\n    pack_multipliers: Mapping[str, float] | None = None,\n) -> str:',
    "style signature",
)
text = replace_once(
    text,
    '    # Chaos не создаёт новый стиль и не смешивает существующие — просто\n',
    '    if pack_multipliers:\n'
    '        for pack_name, multiplier in pack_multipliers.items():\n'
    '            if pack_name in weights:\n'
    '                weights[pack_name] *= max(0.85, min(1.15, float(multiplier)))\n\n'
    '    if chat_native_weight > 0.0 and mode != "serious":\n'
    '        native_multiplier = 1.0\n'
    '        if pack_multipliers:\n'
    '            native_multiplier = max(\n'
    '                0.85,\n'
    '                min(1.15, float(pack_multipliers.get(VOICE_PACK_CHAT_NATIVE, 1.0))),\n'
    '            )\n'
    '        weights[VOICE_PACK_CHAT_NATIVE] = max(0.0, chat_native_weight) * native_multiplier\n\n'
    '    # Chaos не создаёт новый стиль и не смешивает существующие — просто\n',
    "style adaptation",
)
path.write_text(text, encoding="utf-8")


# ---------------- verdict_engine.py ----------------
path = Path("verdict_engine.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '    taunt_already_selected: bool = False,\n    rng=random,\n) -> str | None:',
    '    taunt_already_selected: bool = False,\n    chance_multiplier: float = 1.0,\n    rng=random,\n) -> str | None:',
    "verdict signature",
)
text = replace_once(
    text,
    '    if rng.random() >= VERDICT_CHANCE:\n        return None\n',
    '    effective_chance = max(0.0, min(1.0, VERDICT_CHANCE * chance_multiplier))\n'
    '    if rng.random() >= effective_chance:\n'
    '        return None\n',
    "verdict chance",
)
path.write_text(text, encoding="utf-8")


# ---------------- voice_runtime.py ----------------
path = Path("voice_runtime.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '    serious_topic: bool = False,\n    rng=random,\n) -> VoiceMaterial:',
    '    serious_topic: bool = False,\n    adaptation: dict | None = None,\n    rng=random,\n) -> VoiceMaterial:',
    "voice signature",
)
text = replace_once(
    text,
    '    primary: str | None = None\n',
    '    adaptation = adaptation or {}\n'
    '    taunt_chance = max(0.12, min(0.28, CONFLICT_TAUNT_CHANCE * float(adaptation.get("taunt_multiplier", 1.0))))\n'
    '    layered_chance = max(0.15, min(0.35, LAYERED_JOKE_CHANCE_WITHIN_TAUNT * float(adaptation.get("layered_multiplier", 1.0))))\n'
    '    verdict_multiplier = max(0.85, min(1.15, float(adaptation.get("verdict_multiplier", 1.0))))\n\n'
    '    primary: str | None = None\n',
    "voice adaptation vars",
)
text = replace_once(
    text,
    '        taunt_selected = rng.random() < CONFLICT_TAUNT_CHANCE\n',
    '        taunt_selected = rng.random() < taunt_chance\n',
    "voice taunt chance",
)
text = replace_once(
    text,
    '                rng.random() >= (1.0 - LAYERED_JOKE_CHANCE_WITHIN_TAUNT)\n',
    '                rng.random() >= (1.0 - layered_chance)\n',
    "voice layered chance",
)
text = replace_once(
    text,
    '            taunt_already_selected=taunt_selected,\n            rng=rng,\n',
    '            taunt_already_selected=taunt_selected,\n            chance_multiplier=verdict_multiplier,\n            rng=rng,\n',
    "voice verdict adaptation",
)
path.write_text(text, encoding="utf-8")


# ---------------- bot.py ----------------
path = Path("bot.py")
text = path.read_text(encoding="utf-8")

text = replace_once(
    text,
    'from telegram.constants import ChatAction, ChatType\n',
    'from telegram.constants import ChatAction, ChatType, UpdateType\n',
    "UpdateType import",
)
text = replace_once(
    text,
    '    MessageHandler,\n    filters,\n)',
    '    MessageHandler,\n    MessageReactionHandler,\n    filters,\n)',
    "reaction handler import",
)
text = replace_once(
    text,
    'import aggression_engine\n',
    'import aggression_engine\nimport chat_native_engine\nimport feedback_engine\nimport humanizer_engine\n',
    "engine imports",
)

schema_marker = '''        _ensure_column(
            connection,
            "chat_settings",
            "weekly_report_last_sent_date",
            "weekly_report_last_sent_date TEXT",
        )

        connection.commit()
'''
schema_new = '''        _ensure_column(
            connection,
            "chat_settings",
            "weekly_report_last_sent_date",
            "weekly_report_last_sent_date TEXT",
        )

        # 13-й динамический voice pack: храним только агрегированные
        # слова/короткие фразы, а не архив исходных сообщений.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_native_terms (
                chat_id INTEGER NOT NULL,
                term TEXT NOT NULL,
                occurrences INTEGER NOT NULL DEFAULT 0,
                first_seen TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (chat_id, term)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_native_term_users (
                chat_id INTEGER NOT NULL,
                term TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                first_seen TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (chat_id, term, user_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_native_profiles (
                chat_id INTEGER PRIMARY KEY,
                terms_json TEXT NOT NULL DEFAULT '[]',
                distinct_users INTEGER NOT NULL DEFAULT 0,
                compiled_at TEXT
            )
            """
        )

        # Метаданные только собственных ответов бота. Полный текст ответа
        # здесь не хранится: нужен message_id + тип поведения для реакции.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_response_feedback (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                voice_pack TEXT NOT NULL,
                humor_type TEXT,
                verdict_used INTEGER NOT NULL DEFAULT 0,
                reaction_score REAL NOT NULL DEFAULT 0,
                reaction_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (chat_id, message_id)
            )
            """
        )

        connection.commit()
'''
text = replace_once(text, schema_marker, schema_new, "adaptation schema")

helpers = r'''

def record_chat_native_message_sync(
    chat_id: int,
    user_id: int,
    text: str,
    chat_type: str = "group",
) -> int:
    """Сохраняет только агрегированные кандидаты локального сленга."""

    terms = chat_native_engine.extract_candidate_terms(text)
    if not terms:
        return 0

    with get_db_connection() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO chats (chat_id, chat_type) VALUES (?, ?)",
            (chat_id, chat_type),
        )
        connection.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,),
        )
        for term in terms:
            connection.execute(
                """
                INSERT INTO chat_native_terms (chat_id, term, occurrences)
                VALUES (?, ?, 1)
                ON CONFLICT(chat_id, term) DO UPDATE SET
                    occurrences = occurrences + 1,
                    last_seen = datetime('now')
                """,
                (chat_id, term),
            )
            connection.execute(
                """
                INSERT INTO chat_native_term_users (chat_id, term, user_id)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id, term, user_id) DO UPDATE SET
                    last_seen = datetime('now')
                """,
                (chat_id, term, user_id),
            )
        connection.commit()
    return len(terms)


def get_chat_native_profile_sync(chat_id: int) -> dict[str, Any]:
    with get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT terms_json, distinct_users, compiled_at
            FROM chat_native_profiles
            WHERE chat_id = ?
            """,
            (chat_id,),
        ).fetchone()
    if row is None:
        return {"terms": [], "distinct_users": 0, "compiled_at": None}
    try:
        terms = json.loads(row[0] or "[]")
    except (TypeError, json.JSONDecodeError):
        terms = []
    return {
        "terms": [str(term) for term in terms if str(term).strip()],
        "distinct_users": int(row[1] or 0),
        "compiled_at": row[2],
    }


def refresh_due_chat_native_profiles_sync() -> int:
    """Первый pack собирает после достаточной выборки, затем обновляет раз в неделю."""

    now = datetime.now(timezone.utc)
    refreshed = 0
    with get_db_connection() as connection:
        chat_rows = connection.execute(
            "SELECT DISTINCT chat_id FROM chat_native_terms ORDER BY chat_id"
        ).fetchall()

        for (chat_id_raw,) in chat_rows:
            chat_id = int(chat_id_raw)
            profile_row = connection.execute(
                "SELECT compiled_at FROM chat_native_profiles WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            if profile_row and profile_row[0]:
                try:
                    compiled_at = datetime.fromisoformat(str(profile_row[0]))
                    if compiled_at.tzinfo is None:
                        compiled_at = compiled_at.replace(tzinfo=timezone.utc)
                    if (now - compiled_at).total_seconds() < chat_native_engine.PROFILE_REFRESH_SECONDS:
                        continue
                except ValueError:
                    pass

            stats_rows = connection.execute(
                """
                SELECT terms.term, terms.occurrences, COUNT(users.user_id)
                FROM chat_native_terms AS terms
                LEFT JOIN chat_native_term_users AS users
                  ON users.chat_id = terms.chat_id AND users.term = terms.term
                WHERE terms.chat_id = ?
                GROUP BY terms.term, terms.occurrences
                """,
                (chat_id,),
            ).fetchall()
            distinct_users = int(
                connection.execute(
                    "SELECT COUNT(DISTINCT user_id) FROM chat_native_term_users WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()[0]
            )
            terms = chat_native_engine.compile_profile_terms(stats_rows)
            if not chat_native_engine.profile_is_ready(terms, distinct_users):
                continue

            connection.execute(
                """
                INSERT INTO chat_native_profiles (chat_id, terms_json, distinct_users, compiled_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    terms_json = excluded.terms_json,
                    distinct_users = excluded.distinct_users,
                    compiled_at = excluded.compiled_at
                """,
                (
                    chat_id,
                    json.dumps(list(terms), ensure_ascii=False),
                    distinct_users,
                    now.isoformat(),
                ),
            )
            refreshed += 1

        # Не даём словарю расти бесконечно: старые одноразовые кандидаты
        # исчезают, устойчивые мемы/словечки остаются.
        connection.execute(
            """
            DELETE FROM chat_native_term_users
            WHERE NOT EXISTS (
                SELECT 1 FROM chat_native_terms t
                WHERE t.chat_id = chat_native_term_users.chat_id
                  AND t.term = chat_native_term_users.term
            )
            """
        )
        connection.commit()
    return refreshed


async def refresh_due_chat_native_profiles() -> int:
    return await asyncio.to_thread(refresh_due_chat_native_profiles_sync)


def store_bot_response_feedback_sync(
    chat_id: int,
    message_id: int,
    trace: feedback_engine.ResponseTrace,
) -> None:
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO bot_response_feedback
                (chat_id, message_id, voice_pack, humor_type, verdict_used)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                message_id,
                trace.voice_pack,
                trace.humor_type,
                int(trace.verdict_used),
            ),
        )
        # Последних 500 ответов на чат более чем достаточно для окна 20.
        connection.execute(
            """
            DELETE FROM bot_response_feedback
            WHERE chat_id = ?
              AND rowid NOT IN (
                  SELECT rowid FROM bot_response_feedback
                  WHERE chat_id = ?
                  ORDER BY created_at DESC, message_id DESC
                  LIMIT 500
              )
            """,
            (chat_id, chat_id),
        )
        connection.commit()


def apply_bot_reaction_delta_sync(
    chat_id: int,
    message_id: int,
    score_delta: float,
    count_delta: int,
) -> bool:
    with get_db_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE bot_response_feedback
            SET reaction_score = reaction_score + ?,
                reaction_count = MAX(0, reaction_count + ?)
            WHERE chat_id = ? AND message_id = ?
            """,
            (score_delta, count_delta, chat_id, message_id),
        )
        connection.commit()
        return cursor.rowcount > 0


def get_chat_feedback_adaptation_sync(chat_id: int) -> dict[str, Any]:
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT voice_pack, humor_type, verdict_used,
                   reaction_score, reaction_count
            FROM bot_response_feedback
            WHERE chat_id = ? AND reaction_count > 0
            ORDER BY created_at DESC, message_id DESC
            LIMIT 200
            """,
            (chat_id,),
        ).fetchall()
    return feedback_engine.build_adaptation(
        [
            {
                "voice_pack": row[0],
                "humor_type": row[1],
                "verdict_used": bool(row[2]),
                "reaction_score": float(row[3]),
                "reaction_count": int(row[4]),
            }
            for row in rows
        ]
    )


def get_chat_native_learning_status_sync(chat_id: int) -> dict[str, Any]:
    profile = get_chat_native_profile_sync(chat_id)
    with get_db_connection() as connection:
        candidate_terms = int(
            connection.execute(
                "SELECT COUNT(*) FROM chat_native_terms WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()[0]
        )
        distinct_users = int(
            connection.execute(
                "SELECT COUNT(DISTINCT user_id) FROM chat_native_term_users WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()[0]
        )
    adaptation = get_chat_feedback_adaptation_sync(chat_id)
    return {
        **profile,
        "candidate_terms": candidate_terms,
        "observed_users": distinct_users,
        "reacted_messages": int(adaptation.get("reacted_messages", 0)),
    }

'''
text = replace_once(
    text,
    'initialize_stats_database()\n\n\ndef get_user_settings_sync(',
    'initialize_stats_database()\n' + helpers + '\ndef get_user_settings_sync(',
    "db helpers",
)

# Add adaptation scheduler next to the existing daily title scheduler.
scheduler_marker = '''async def daily_title_scheduler_loop(application: Application) -> None:
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
scheduler_new = scheduler_marker + '''CHAT_NATIVE_REFRESH_CHECK_INTERVAL_SECONDS = 6 * 60 * 60


async def chat_native_refresh_loop(application: Application) -> None:
    """Периодически собирает/обновляет 13-й voice pack каждого чата."""

    del application
    while True:
        try:
            refreshed = await refresh_due_chat_native_profiles()
            if refreshed:
                logging.info("Обновлены chat_native профили: %s", refreshed)
        except Exception as error:
            logging.warning("Ошибка обновления chat_native: %s", error)
        await asyncio.sleep(CHAT_NATIVE_REFRESH_CHECK_INTERVAL_SECONDS)


'''
text = replace_once(text, scheduler_marker, scheduler_new, "native scheduler")

# Startup task.
startup_old = '''    application.create_task(
        daily_title_scheduler_loop(application),
        name="daily_title_scheduler",
    )
'''
startup_new = startup_old + '''    application.create_task(
        chat_native_refresh_loop(application),
        name="chat_native_refresh",
    )
'''
text = replace_once(text, startup_old, startup_new, "startup native task")

# Observe every non-command human group message before direct-address early return.
observe_marker = '''    # Команды в память не записываем
    if text.startswith("/"):
        return

    bot_username = await get_bot_username(
'''
observe_new = '''    # Команды в память не записываем
    if text.startswith("/"):
        return

    # 13-й pack учится и на прямых обращениях, и на фоне чата. Полный
    # текст в SQLite не сохраняется — только извлечённые агрегированные термы.
    if not is_serious_text(text.lower()):
        await asyncio.to_thread(
            record_chat_native_message_sync,
            update.effective_chat.id,
            update.effective_user.id,
            text,
            str(update.effective_chat.type),
        )

    bot_username = await get_bot_username(
'''
text = replace_once(text, observe_marker, observe_new, "native observation")

# Replace voice-pack planning block with adaptive + virtual chat_native pack.
pattern = re.compile(
    r'''        voice_pack = style_engine\.choose_voice_pack\(\n            style_engine\.VoicePackContext\(.*?        current_instruction \+= voice_runtime\.build_voice_instruction\(voice_material\)\n''',
    re.S,
)
match = pattern.search(text)
if not match:
    raise RuntimeError("marker not found: build_full_system voice block")
replacement = '''        adaptation = (
            get_chat_feedback_adaptation_sync(chat_id)
            if chat_id is not None and chat_type in ("group", "supergroup")
            else feedback_engine.build_adaptation(())
        )
        native_profile = (
            get_chat_native_profile_sync(chat_id)
            if chat_id is not None and chat_type in ("group", "supergroup")
            else {"terms": []}
        )
        native_terms = tuple(native_profile.get("terms") or ())
        native_weight = (
            chat_native_engine.base_pack_weight(conversation_mode)
            if native_terms
            else 0.0
        )

        voice_pack = style_engine.choose_voice_pack(
            style_engine.VoicePackContext(
                conversation_mode=conversation_mode,
                selected_character=str(settings.get("character", "classic")),
                serious_topic=(conversation_mode == "serious"),
            ),
            chat_native_weight=native_weight,
            pack_multipliers=adaptation.get("pack_multipliers"),
        )
        length_plan = style_engine.choose_response_length(
            chat_id if chat_id is not None else 0,
            style_engine.ResponseLengthContext(
                user_text=style_text,
                conversation_mode=conversation_mode,
                message_intent=resolved_intent,
                response_preference=str(settings.get("response_length", "normal")),
                serious_topic=(conversation_mode == "serious"),
                character_state=character_state,
            ),
            record=(chat_id is not None),
        )
        current_instruction += style_engine.build_length_instruction(length_plan)

        voice_material = None
        if voice_pack == style_engine.VOICE_PACK_CHAT_NATIVE:
            current_instruction += chat_native_engine.build_pack_instruction(
                native_terms,
                conversation_mode=conversation_mode,
                roughness=str(settings.get("roughness", "medium")),
            )
        else:
            voice_material = voice_runtime.choose_voice_material(
                voice_pack,
                conversation_mode=conversation_mode,
                roughness=str(settings.get("roughness", "medium")),
                serious_topic=(conversation_mode == "serious"),
                adaptation=adaptation,
            )
            current_instruction += voice_runtime.build_voice_instruction(voice_material)

        feedback_engine.set_current_trace(
            feedback_engine.ResponseTrace(
                chat_id=chat_id,
                chat_type=chat_type,
                voice_pack=voice_pack,
                humor_type=(voice_material.category if voice_material else None),
                verdict_used=bool(voice_material and voice_material.verdict),
                serious_topic=(conversation_mode == "serious"),
                conversation_mode=conversation_mode,
                message_intent=resolved_intent,
            )
        )
'''
text = text[: match.start()] + replacement + text[match.end() :]

# Every Gemini request starts with a clean task-local trace.
text = replace_once(
    text,
    '    """Отправляет запрос Gemini с тремя попытками."""\n\n    if isinstance(contents, str):',
    '    """Отправляет запрос Gemini с тремя попытками."""\n\n    feedback_engine.reset_current_trace()\n\n    if isinstance(contents, str):',
    "trace reset",
)

# Replace send_answer as one unit.
send_pattern = re.compile(
    r'async def send_answer\(.*?\nasync def answer_button_callback\(',
    re.S,
)
send_match = send_pattern.search(text)
if not send_match:
    raise RuntimeError("marker not found: send_answer function")
new_send = r'''async def send_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    force_voice: bool = False,
    show_buttons: bool = False,
    source_user_text: str | None = None,
) -> None:
    """Отправляет voice/text; в групповой болтовне иногда делает ответ человечнее."""

    message = update.effective_message
    if not message:
        return

    answer_text = (text or "").strip()
    if not answer_text:
        answer_text = "Яйцеслав задумался и ничего не изрёк. Редкий анлак."

    use_voice = force_voice or voice_mode_enabled(context)
    if use_voice:
        try:
            await send_voice_answer(update, answer_text)
            return
        except Exception as error:
            logging.exception("Ошибка голосового ответа: %s", error)
            await message.reply_text("Голосовой тракт охрип. Держи ответ текстом.")

    trace = feedback_engine.get_current_trace()
    if source_user_text is None:
        plan = humanizer_engine.HumanizedReply((answer_text,), (0.0,))
    else:
        plan = humanizer_engine.humanize_reply(
            answer_text,
            user_text=source_user_text,
            trace=trace,
        )

    for message_index, planned_text in enumerate(plan.messages):
        delay = plan.delays[message_index] if message_index < len(plan.delays) else 0.0
        if delay > 0:
            await asyncio.sleep(delay)

        for position in range(0, len(planned_text), 4000):
            is_last_chunk = position + 4000 >= len(planned_text)
            is_last_planned = message_index == len(plan.messages) - 1
            reply_markup = None
            if (
                show_buttons
                and update.effective_chat
                and update.effective_chat.type == ChatType.PRIVATE
                and is_last_chunk
                and is_last_planned
            ):
                reply_markup = build_private_answer_keyboard()

            sent_message = await message.reply_text(
                planned_text[position:position + 4000],
                reply_markup=reply_markup,
            )

            is_typo_correction = (
                plan.effect == "typo_correction" and message_index == 1
            )
            if (
                trace is not None
                and update.effective_chat
                and update.effective_chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
                and not is_typo_correction
            ):
                await asyncio.to_thread(
                    store_bot_response_feedback_sync,
                    update.effective_chat.id,
                    sent_message.message_id,
                    trace,
                )


async def answer_button_callback('''
text = text[: send_match.start()] + new_send + text[send_match.end() :]

# Humanizer only on the primary conversational text path.
normal_send_old = '''            show_buttons=True,
        )
        
        await increment_stat(
            "bot_answers"
        )    
'''
normal_send_new = '''            show_buttons=True,
            source_user_text=user_text,
        )
        
        await increment_stat(
            "bot_answers"
        )    
'''
# There are two show_buttons=True paths; target the one closest to answer_text_message.
answer_start = text.find('async def answer_text_message(')
if answer_start < 0:
    raise RuntimeError("answer_text_message not found")
segment = text[answer_start:]
if normal_send_old not in segment:
    raise RuntimeError("normal text send marker not found")
segment = segment.replace(normal_send_old, normal_send_new, 1)
text = text[:answer_start] + segment

# Reaction handler + status command before Gemini version command.
reaction_code = r'''

async def message_reaction_feedback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Учит вкус конкретного чата по реакциям людей на сообщения Яйцеслава."""

    del context
    reaction = update.message_reaction
    if reaction is None:
        return

    score_delta, count_delta = feedback_engine.reaction_delta(
        reaction.old_reaction,
        reaction.new_reaction,
    )
    if score_delta == 0 and count_delta == 0:
        return

    await asyncio.to_thread(
        apply_bot_reaction_delta_sync,
        reaction.chat.id,
        reaction.message_id,
        score_delta,
        count_delta,
    )


async def chat_native_status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Показывает, насколько 13-й пакет уже освоил конкретный чат."""

    del context
    if not update.message or not update.effective_chat:
        return
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text("chat_native существует только в группах.")
        return

    status = await asyncio.to_thread(
        get_chat_native_learning_status_sync,
        update.effective_chat.id,
    )
    terms = status.get("terms") or []
    if terms:
        learned = ", ".join(terms[:12])
        state = "готов и используется как отдельный 13-й voice pack"
    else:
        learned = "пока недостаточно устойчивых словечек"
        state = "ещё набирает выборку"

    await update.message.reply_text(
        "chat_native этого чата:\n"
        f"Статус: {state}\n"
        f"Участников в обучающей выборке: {status.get('observed_users', 0)}\n"
        f"Кандидатов-термов: {status.get('candidate_terms', 0)}\n"
        f"Ответов с реакционной обратной связью: {status.get('reacted_messages', 0)}\n"
        f"Освоено: {learned}"
    )

'''
text = replace_once(
    text,
    '\nasync def gemini_version_command(\n',
    reaction_code + '\nasync def gemini_version_command(\n',
    "reaction callback insertion",
)

# Help line.
text = replace_once(
    text,
    '    "/title_status — статус автоматического титула дня\\n"\n)',
    '    "/title_status — статус автоматического титула дня\\n"\n'
    '    "/chat_native_status — чему Яйцеслав уже научился у этого чата\\n"\n)',
    "help native status",
)

# Register status command.
register_marker = '''    application.add_handler(
        CommandHandler(
            "title_status",
            title_status_command,
        )
    )
'''
register_new = register_marker + '''    application.add_handler(
        CommandHandler(
            "chat_native_status",
            chat_native_status_command,
        )
    )
'''
text = replace_once(text, register_marker, register_new, "status command registration")

# Register reaction handler before ordinary message handlers.
handler_marker = '''    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            answer_photo,
        )
    )
'''
handler_new = '''    application.add_handler(
        MessageReactionHandler(
            message_reaction_feedback_handler,
        )
    )
''' + handler_marker
text = replace_once(text, handler_marker, handler_new, "reaction handler registration")

# Explicitly ask Telegram for message_reaction updates.
text = replace_once(
    text,
    '''    application.run_polling(
        drop_pending_updates=True
    )
''',
    '''    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=[
            UpdateType.MESSAGE,
            UpdateType.EDITED_MESSAGE,
            UpdateType.CALLBACK_QUERY,
            UpdateType.MESSAGE_REACTION,
        ],
    )
''',
    "allowed reaction updates",
)

path.write_text(text, encoding="utf-8")

print("chat adaptation patch applied")
