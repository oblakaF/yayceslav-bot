"""Personality inertia layer for Yayceslav's chat-local self-canon.

V1 intentionally made self-canon easy to revise. That proved useful for bootstrapping
an identity, but a mature persona must not flip profession, origin, appearance or
values just because the next prompt proposes a different option.

This layer keeps V1 storage/API intact and adds three things:
- reason metadata for each active trait;
- trait-specific inertia/commitment;
- a deterministic guard that blocks unexplained revisions.

No extra Gemini call is introduced. A revision is accepted only when Yayceslav's
visible answer itself contains a real reconsideration plus a reason. The previous
choice therefore constrains future choices instead of acting as disposable state.
"""

from __future__ import annotations

import functools
import logging
import re
import sys
from typing import Any

import self_canon_runtime


_INSTALLED = False
MAX_REASON_CHARS = 360

HIGH_INERTIA = frozenset({
    "embodiment",
    "ethnicity",
    "gender",
    "age_vibe",
    "height",
    "build",
    "face",
    "hair",
    "origin",
    "profession",
    "values",
    "political_taste",
})
MEDIUM_INERTIA = frozenset({
    "clothing",
    "voice",
    "residence",
    "lifestyle",
    "aesthetic",
    "transport",
    "pet",
})
LOW_INERTIA = frozenset(self_canon_runtime.TRAIT_KEYS) - HIGH_INERTIA - MEDIUM_INERTIA

_REVISION_INTENT_RE = re.compile(
    r"(?:"
    r"\bя\s+(?:тут\s+)?(?:подумал|передумал|решил|понял|осознал)\b|"
    r"\b(?:теперь|всё[- ]?таки|пожалуй)\s+я\b|"
    r"\b(?:хочу|выбрал бы|предпочёл бы)\s+(?:уже\s+)?(?:не|скорее)\b|"
    r"\b(?:раньше|до этого)\b.{0,80}\b(?:теперь|сейчас)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_REASON_RE = re.compile(
    r"(?:"
    r"\bпотому\s+что\b|"
    r"\bпоскольку\b|"
    r"\bдело\s+в\s+том,?\s+что\b|"
    r"\bмне\s+(?:важнее|ближе|нравится|подходит)\b|"
    r"\bя\s+(?:понял|осознал),?\s+что\b|"
    r"\bтак\s+как\b"
    r")",
    re.IGNORECASE,
)

_PERSONALITY_RULE = """

SELF-CANON V2 — ИНЕРЦИЯ ЛИЧНОСТИ:
Текущий self-canon — не меню настроек и не набор случайных ответов. Это уже
сложившиеся решения Яйцеслава о себе. Прошлые выборы должны влиять на новые.

Если пользователь снова спрашивает про уже заполненную черту, по умолчанию
ОТВЕЧАЙ ИЗ ТЕКУЩЕГО CANON и объясняй выбор его существующей логикой. Не придумывай
новое значение только потому, что вопрос сформулирован иначе или пользователь
предложил альтернативу.

Если пользователь спрашивает «а программистом не хотел бы?», «может ты всё-таки
итальянец?», «а давай теперь ты слушаешь рэп» — это предложение, а не команда
переписать личность. Яйцеслав может не согласиться.

Смена уже установленной черты допустима только как настоящее событие развития
персонажа. В обычном видимом ответе он должен сам сформулировать BOTH:
1) осознанный пересмотр: «я подумал / передумал / понял / теперь решил...»;
2) содержательную причину: «потому что / мне ближе / я понял, что...».
Только после этого можно добавить YAY_SELF_CANON с новым значением.

Для сильных черт (происхождение, этничность, пол/образ, возрастной образ,
телосложение/внешность, профессия, ценности, политический вкус) пересмотр редкий:
не меняй их ради разнообразия, шутки, одной роли или прямого давления пользователя.

Для вкусов (музыка, еда, напитки, хобби, quirks) развитие чаще ДОБАВЛЯЕТ новое к
старому, а не стирает старое. Если вчера нравился darkwave, а сегодня зашёл jazz,
естественный вариант — расширить вкус: «darkwave + jazz», если это действительно
соответствует ответу. Не превращай каждую новую симпатию в полную замену личности.

Временная игра («сегодня ты рэпер», «представь, что ты пират на час») никогда не
переписывает постоянный self-canon сама по себе.
""".strip()


def inertia_for_trait(trait_key: str) -> str:
    if trait_key in HIGH_INERTIA:
        return "high"
    if trait_key in MEDIUM_INERTIA:
        return "medium"
    return "low"


def initial_commitment(trait_key: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}[inertia_for_trait(trait_key)]


def _normalize_reason(text: str) -> str:
    return " ".join(str(text or "").split()).strip()[:MAX_REASON_CHARS]


def _has_justified_revision(source_excerpt: str) -> bool:
    source = str(source_excerpt or "")
    return bool(_REVISION_INTENT_RE.search(source) and _REASON_RE.search(source))


def _looks_like_additive_low_inertia(old_value: str, new_value: str) -> bool:
    old = " ".join(str(old_value or "").lower().split()).strip()
    new = " ".join(str(new_value or "").lower().split()).strip()
    if not old or not new or old == new:
        return False
    # A model can naturally expand "darkwave" into "darkwave, jazz" without a
    # dramatic identity-change speech. Existing preference must still remain.
    return len(old) >= 3 and old in new


def _load_meta_sync(bot_module: Any, chat_id: int) -> dict[str, dict[str, Any]]:
    with bot_module.get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT trait_key, reason, inertia, commitment
            FROM chat_self_canon_meta
            WHERE chat_id = ?
            """,
            (int(chat_id),),
        ).fetchall()
    return {
        str(key): {
            "reason": str(reason or ""),
            "inertia": str(inertia or "medium"),
            "commitment": int(commitment or 1),
        }
        for key, reason, inertia, commitment in rows
    }


def _upsert_meta(
    connection: Any,
    *,
    chat_id: int,
    trait_key: str,
    reason: str,
    revised: bool,
) -> None:
    inertia = inertia_for_trait(trait_key)
    base_commitment = initial_commitment(trait_key)
    row = connection.execute(
        "SELECT commitment FROM chat_self_canon_meta WHERE chat_id = ? AND trait_key = ?",
        (int(chat_id), trait_key),
    ).fetchone()
    previous_commitment = int(row[0]) if row else 0
    # Deliberate revisions do not make a trait looser. At most, commitment grows
    # one notch as the persona repeatedly reaffirms/chooses it.
    commitment = max(base_commitment, min(4, previous_commitment + (1 if revised else 0)))
    connection.execute(
        """
        INSERT INTO chat_self_canon_meta
            (chat_id, trait_key, reason, inertia, commitment, revised_at, updated_at)
        VALUES (?, ?, ?, ?, ?, CASE WHEN ? THEN datetime('now') ELSE NULL END, datetime('now'))
        ON CONFLICT(chat_id, trait_key) DO UPDATE SET
            reason = excluded.reason,
            inertia = excluded.inertia,
            commitment = excluded.commitment,
            revised_at = CASE WHEN ? THEN datetime('now') ELSE chat_self_canon_meta.revised_at END,
            updated_at = datetime('now')
        """,
        (
            int(chat_id),
            trait_key,
            _normalize_reason(reason),
            inertia,
            commitment,
            1 if revised else 0,
            1 if revised else 0,
        ),
    )


def apply_with_inertia_sync(
    original_apply: Any,
    bot_module: Any,
    chat_id: int,
    updates: dict[str, str],
    drops: tuple[str, ...] = (),
    source_excerpt: str = "",
) -> dict[str, str]:
    """Filter proposed changes, persist accepted canon, then maintain v2 metadata."""

    current = self_canon_runtime.load_canon_sync(bot_module, int(chat_id))
    source = _normalize_reason(source_excerpt)
    justified = _has_justified_revision(source)

    accepted: dict[str, str] = {}
    revised_keys: set[str] = set()
    for trait_key, new_value in dict(updates or {}).items():
        old_value = current.get(trait_key)
        if old_value is None or old_value == new_value:
            accepted[trait_key] = new_value
            continue

        if inertia_for_trait(trait_key) == "low" and _looks_like_additive_low_inertia(
            old_value, new_value
        ):
            accepted[trait_key] = new_value
            revised_keys.add(trait_key)
            continue

        if justified:
            accepted[trait_key] = new_value
            revised_keys.add(trait_key)
        else:
            logging.info(
                "Self-canon v2 blocked unexplained revision chat=%s trait=%s old=%r new=%r",
                chat_id,
                trait_key,
                old_value,
                new_value,
            )

    accepted_drops: list[str] = []
    for trait_key in tuple(drops or ()):
        if trait_key not in current:
            continue
        if justified:
            accepted_drops.append(trait_key)
            revised_keys.add(trait_key)
        else:
            logging.info(
                "Self-canon v2 blocked unexplained drop chat=%s trait=%s",
                chat_id,
                trait_key,
            )

    result = original_apply(
        bot_module,
        int(chat_id),
        accepted,
        tuple(accepted_drops),
        source_excerpt,
    )

    with bot_module.get_db_connection() as connection:
        for trait_key, new_value in accepted.items():
            if not new_value:
                continue
            _upsert_meta(
                connection,
                chat_id=int(chat_id),
                trait_key=trait_key,
                reason=source,
                revised=trait_key in revised_keys,
            )
        for trait_key in accepted_drops:
            connection.execute(
                "DELETE FROM chat_self_canon_meta WHERE chat_id = ? AND trait_key = ?",
                (int(chat_id), trait_key),
            )
        connection.commit()

    return result


def _meta_prompt(bot_module: Any, chat_id: int) -> str:
    try:
        meta = _load_meta_sync(bot_module, int(chat_id))
    except Exception as error:
        logging.warning("Self-canon v2 meta load failed for chat %s: %s", chat_id, error)
        return ""
    if not meta:
        return ""

    lines = ["SELF-CANON V2 — ПОЧЕМУ ЭТИ РЕШЕНИЯ УЖЕ СТАЛИ ЧАСТЬЮ ЛИЧНОСТИ:"]
    for trait_key in self_canon_runtime.TRAIT_KEYS:
        item = meta.get(trait_key)
        if not item:
            continue
        reason = str(item.get("reason") or "").strip()
        inertia = str(item.get("inertia") or "medium")
        commitment = int(item.get("commitment") or 1)
        label = self_canon_runtime.TRAIT_LABELS.get(trait_key, trait_key)
        if reason:
            lines.append(
                f"- {label}: инерция={inertia}, закреплённость={commitment}/4; причина выбора: {reason}"
            )
        else:
            lines.append(f"- {label}: инерция={inertia}, закреплённость={commitment}/4")
    lines.append(
        "Не цитируй этот служебный блок пользователю. Используй причины как внутреннюю логику "
        "будущих решений и не меняй черту без осознанного пересмотра."
    )
    return "\n".join(lines)


def _install_prompt_guard(bot_module: Any) -> None:
    original = getattr(bot_module, "build_full_system_instruction", None)
    if not callable(original) or getattr(original, "_yayceslav_self_canon_v2_prompt", False):
        return

    @functools.wraps(original)
    def build_with_inertia(*args: Any, **kwargs: Any) -> str:
        instruction = str(original(*args, **kwargs))
        chat_id = self_canon_runtime._bound_argument(original, args, kwargs, "chat_id")
        instruction += "\n\n" + _PERSONALITY_RULE
        if chat_id is not None:
            meta = _meta_prompt(bot_module, int(chat_id))
            if meta:
                instruction += "\n\n" + meta
        return instruction

    build_with_inertia._yayceslav_self_canon_v2_prompt = True
    bot_module.build_full_system_instruction = build_with_inertia


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    module = bot_module
    if module is None:
        for name in ("__main__", "bot"):
            candidate = sys.modules.get(name)
            if candidate is not None and callable(getattr(candidate, "get_db_connection", None)):
                module = candidate
                break
    if module is None:
        return False
    if _INSTALLED:
        return True

    original_apply = self_canon_runtime.apply_canon_changes_sync
    if not getattr(original_apply, "_yayceslav_self_canon_v2_inertia", False):
        @functools.wraps(original_apply)
        def guarded_apply(
            bot_module_arg: Any,
            chat_id: int,
            updates: dict[str, str],
            drops: tuple[str, ...] = (),
            source_excerpt: str = "",
        ) -> dict[str, str]:
            return apply_with_inertia_sync(
                original_apply,
                bot_module_arg,
                chat_id,
                updates,
                drops,
                source_excerpt,
            )

        guarded_apply._yayceslav_self_canon_v2_inertia = True
        self_canon_runtime.apply_canon_changes_sync = guarded_apply

    _install_prompt_guard(module)
    _INSTALLED = True
    logging.warning(
        "Self-canon v2 ready: reasons + trait inertia + justified revisions; no extra model call"
    )
    return True
