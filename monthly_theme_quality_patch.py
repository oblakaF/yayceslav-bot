from __future__ import annotations

import whoami_profile_v3_runtime as profile_runtime


_PATCHED = False


def _themes_monthly_ranked(bot_module, chat_id: int, user_id: int) -> list[str]:
    """Return only recurring, meaningful themes from the current calendar month.

    A recent one-off swear/verb is not a theme. Recurrence beats recency.
    """
    month_start = bot_module.current_msk_datetime().date().replace(day=1).isoformat()

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

        # Phrases are useful only when they recur; single words need a little
        # more evidence before being promoted to a monthly theme.
        count = int(occurrences or 0)
        if len(meaningful) == 1 and count < 3:
            continue

        score = float(count) * (1.18 if len(meaningful) >= 2 else 1.0)
        candidates.append((score, clean, norm))
        seen.add(norm)

    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [item[1] for item in candidates[:3]]


def install() -> None:
    global _PATCHED
    if _PATCHED:
        return
    profile_runtime._themes_sync = _themes_monthly_ranked
    _PATCHED = True


install()
