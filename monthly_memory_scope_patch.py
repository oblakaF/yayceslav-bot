from __future__ import annotations

import chat_native_engine
import member_profile_runtime as member_runtime
import whoami_profile_v3_runtime as profile_runtime


_PATCHED = False
# Kept as a compatibility reference only. The calendar-month runtime no longer
# calls the legacy initializer because it would create the unused all-time
# member_word_counts table. Existing production tables are intentionally not
# dropped or migrated in this safe cleanup.
_ORIGINAL_PROFILE_INIT = profile_runtime._initialize_tables

# These may legitimately be frequent personal words, so they can still appear
# as "favorite word". They are not topics, however, and must never be fed to the
# dossier verdict generator as if they described a person's interests.
_GENERIC_SINGLE_THEME_WORDS = {
    "вроде", "всех", "всем", "всего", "весь", "вся", "все",
    "починил", "починила", "починили", "починить", "почини", "чинить",
    "сделал", "сделала", "сделали", "делал", "делала", "делали",
    "проверил", "проверила", "проверили", "проверить", "проверь",
    "говорил", "говорила", "говорили", "сказали", "сказать",
    "посмотрел", "посмотрела", "посмотрели", "посмотреть", "смотри",
    "увидел", "увидела", "увидели", "видел", "видела",
    "понял", "поняла", "поняли", "понимаю", "понять",
    "хотел", "хотела", "хотели", "хотеть",
    "решил", "решила", "решили", "решить",
    "получил", "получила", "получили", "получить",
    "работает", "работал", "работала", "работали", "работать",
    "нравится", "нравилось", "понравилось",
    "кажется", "кажись", "наверное", "наверно", "скорее",
    "пока", "прям", "точно", "реально", "правда", "просто",
}


def _month(bot_module) -> str:
    now = bot_module.current_msk_datetime()
    return f"{now.year:04d}-{now.month:02d}"


def _month_start(bot_module) -> str:
    return bot_module.current_msk_datetime().date().replace(day=1).isoformat()


def _record_member_terms_monthly(bot_module, chat_id: int, user_id: int, text: str) -> int:
    terms = tuple(
        term
        for term in chat_native_engine.extract_candidate_terms(text or "")
        if member_runtime._safe_callback_term(term)
    )
    if not terms:
        return 0

    month_start = _month_start(bot_module)
    with bot_module.get_db_connection() as connection:
        for term in terms:
            old = connection.execute(
                """
                SELECT occurrences, last_seen
                FROM member_callback_terms
                WHERE chat_id = ? AND user_id = ? AND term = ?
                """,
                (chat_id, user_id, term),
            ).fetchone()
            if old and str(old[1] or "")[:10] >= month_start:
                connection.execute(
                    """
                    UPDATE member_callback_terms
                    SET occurrences = occurrences + 1,
                        last_seen = datetime('now')
                    WHERE chat_id = ? AND user_id = ? AND term = ?
                    """,
                    (chat_id, user_id, term),
                )
            elif old:
                connection.execute(
                    """
                    UPDATE member_callback_terms
                    SET occurrences = 1,
                        first_seen = datetime('now'),
                        last_seen = datetime('now'),
                        last_used_at = NULL
                    WHERE chat_id = ? AND user_id = ? AND term = ?
                    """,
                    (chat_id, user_id, term),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO member_callback_terms
                        (chat_id, user_id, term, occurrences)
                    VALUES (?, ?, ?, 1)
                    """,
                    (chat_id, user_id, term),
                )
        connection.commit()
    return len(terms)


def _load_member_memory_monthly(bot_module, chat_id: int, user_id: int):
    month_start = _month_start(bot_module)
    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT term, occurrences, last_used_at
            FROM member_callback_terms
            WHERE chat_id = ? AND user_id = ?
              AND date(last_seen) >= date(?)
            ORDER BY
                CASE
                    WHEN last_used_at IS NULL THEN 0
                    WHEN last_used_at < datetime('now', '-18 hours') THEN 1
                    ELSE 2
                END,
                last_seen DESC,
                occurrences DESC
            LIMIT 20
            """,
            (chat_id, user_id, month_start),
        ).fetchall()

    callbacks: list[str] = []
    for term, _count, last_used in rows:
        if last_used:
            continue
        callbacks.append(str(term))
        if len(callbacks) >= member_runtime.PROFILE_CALLBACK_TERMS:
            break

    return {
        "callback_terms": callbacks,
        "favorite_word": None,
        "favorite_word_count": 0,
    }


def _profile_init_monthly(bot_module) -> None:
    with bot_module.get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS member_word_counts_monthly (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                month TEXT NOT NULL,
                word TEXT NOT NULL,
                occurrences INTEGER NOT NULL DEFAULT 0,
                first_seen TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (chat_id, user_id, month, word)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_member_word_counts_monthly_rank
            ON member_word_counts_monthly(chat_id, user_id, month, occurrences DESC, last_seen DESC)
            """
        )
        connection.commit()


def _record_words_monthly(bot_module, chat_id: int, user_id: int, text: str) -> None:
    words = [
        profile_runtime._normalize_word(word)
        for word in profile_runtime._WORD_RE.findall(text or "")
    ]
    words = [word for word in words if profile_runtime._display_word_ok(word)]
    if not words:
        return

    current_month = _month(bot_module)
    with bot_module.get_db_connection() as connection:
        for word in words:
            connection.execute(
                """
                INSERT INTO member_word_counts_monthly
                    (chat_id, user_id, month, word, occurrences)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(chat_id, user_id, month, word) DO UPDATE SET
                    occurrences = occurrences + 1,
                    last_seen = datetime('now')
                """,
                (chat_id, user_id, current_month, word),
            )
        connection.commit()


def _favorite_word_monthly(bot_module, chat_id: int, user_id: int):
    current_month = _month(bot_module)
    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT word, occurrences
            FROM member_word_counts_monthly
            WHERE chat_id = ? AND user_id = ? AND month = ?
              AND occurrences >= 2
            ORDER BY occurrences DESC, last_seen DESC, word ASC
            LIMIT 20
            """,
            (chat_id, user_id, current_month),
        ).fetchall()
    for word, count in rows:
        if profile_runtime._display_word_ok(str(word)):
            return str(word), int(count)
    return None, 0


def _themes_monthly(bot_module, chat_id: int, user_id: int) -> list[str]:
    """Recurring semantic current-month themes; recurrence beats recency."""
    month_start = _month_start(bot_module)
    with bot_module.get_db_connection() as connection:
        try:
            rows = connection.execute(
                """
                SELECT term, occurrences, last_seen
                FROM member_callback_terms
                WHERE chat_id = ? AND user_id = ?
                  AND date(last_seen) >= date(?)
                  AND occurrences >= 2
                ORDER BY occurrences DESC, last_seen DESC, term ASC
                LIMIT 80
                """,
                (chat_id, user_id, month_start),
            ).fetchall()
        except Exception:
            rows = []

    candidates: list[tuple[float, str, str]] = []
    seen: set[str] = set()
    for term, occurrences, _last_seen in rows:
        clean = str(term or "").strip()
        norm = profile_runtime._normalize_word(clean)
        if not profile_runtime._theme_ok(clean) or norm in seen:
            continue

        words = [
            profile_runtime._normalize_word(word)
            for word in profile_runtime._WORD_RE.findall(clean)
        ]
        meaningful = [
            word
            for word in words
            if len(word) >= 3 and word not in profile_runtime._THEME_NOISE
        ]
        if not meaningful:
            continue

        count = int(occurrences or 0)
        if len(meaningful) == 1:
            # Generic predicates/pronouns/adverbs are not topics regardless of
            # frequency. A legitimate one-word subject (Steam, крипта, котята,
            # Abaqus...) needs a little more recurrence than a multi-word topic.
            if meaningful[0] in _GENERIC_SINGLE_THEME_WORDS:
                continue
            if count < 4:
                continue
        elif count < 2:
            continue

        score = float(count) * (1.25 if len(meaningful) >= 2 else 1.0)
        candidates.append((score, clean, norm))
        seen.add(norm)

    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [item[1] for item in candidates[:3]]


def install() -> None:
    global _PATCHED
    if _PATCHED:
        return

    member_runtime._record_member_terms_sync = _record_member_terms_monthly
    member_runtime._load_member_memory_sync = _load_member_memory_monthly
    profile_runtime._initialize_tables = _profile_init_monthly
    profile_runtime._record_words_sync = _record_words_monthly
    profile_runtime._favorite_word_sync = _favorite_word_monthly
    profile_runtime._themes_sync = _themes_monthly
    _PATCHED = True


install()
