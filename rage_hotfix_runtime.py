"""Production guard for short insult detection and compact RAGE replies.

The live chat exposed two gaps that prompt wording alone could not solve:
1) many short Russian insults were not classified as hostile at all;
2) once hot, Gemini could still answer with long de-escalation lectures.

This runtime adds no model calls and no persistent storage. It extends hostile
classification, records one bounded heat event per real text turn (deduping
immediate retries), appends a final no-deescalation RAGE instruction, and hard
caps already-hot text replies after generation.
"""

from __future__ import annotations

import functools
import logging
import re
import sys
import time
from typing import Any, Mapping, Sequence

import hostile_streak_engine


_INSTALLED = False
_GROUP_CHAT_TYPES = {"group", "supergroup"}
RAGE_MAX_CHARS = 320
RAGE_MAX_SENTENCES = 3
_DEDUPE_SECONDS = 3.0
_RECENT_MAX = 256
_RECENT_HOSTILE_TURNS: dict[tuple[int, int], tuple[str, float]] = {}

# Deliberately focused on direct abuse/provocation seen in real Telegram use.
# It is not a generic profanity detector: neutral profanity in an ordinary
# sentence should not automatically start a fight.
EXTRA_HOSTILE_RE = re.compile(
    r"(?:"
    r"^\s*(?:"
    r"хуе?сос\w*|хуйсос\w*|"
    r"псин\w*|п[её]с\s+еблив\w*|"
    r"ушл[её]п\w*|чучел\w*|"
    r"обоссан\w*|"
    r"поплачь(?:\s+поплачь)?|"
    r"слился(?:\s+маленьк\w*)?|"
    r"нищ(?:ий|ая|ее|ие)\s+ху[йя]\w*"
    r")[.!?,\s]*$|"
    r"\b(?:ты|тебя|тебе|твой|твоя|твои)\b.{0,24}\b(?:"
    r"хуе?сос\w*|хуйсос\w*|псин\w*|ушл[её]п\w*|чучел\w*|обоссан\w*"
    r")\b|"
    r"\b(?:хуе?сос\w*|хуйсос\w*|псин\w*|ушл[её]п\w*|чучел\w*)\b.{0,20}\b(?:"
    r"ты|тебя|тебе"
    r")\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_DEESCALATION_PHRASES = (
    "не собираюсь продолжать",
    "конструктивного диалога",
    "конструктивный диалог",
    "не вижу смысла",
    "общение окончено",
    "диалог окончен",
    "поставить точку",
    "выбери другую мишень",
    "оставь мои сообщения в покое",
    "я на этот балаган больше не отвлекаюсь",
)


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "build_full_system_instruction", None)):
            return module
    return None


def _call_argument(
    args: Sequence[Any],
    kwargs: Mapping[str, Any],
    *,
    name: str,
    position: int,
    default: Any = None,
) -> Any:
    if name in kwargs:
        return kwargs[name]
    if len(args) > position:
        return args[position]
    return default


def is_extra_hostile(text: str) -> bool:
    return bool(EXTRA_HOSTILE_RE.search(" ".join(str(text or "").split()).strip()))


def _is_hostile(bot_module: Any, text: str) -> bool:
    value = str(text or "")
    if is_extra_hostile(value):
        return True
    pattern = getattr(bot_module, "HOSTILE_RE", None)
    try:
        return bool(pattern and pattern.search(value))
    except Exception:
        return False


def _observe_hostile_turn_once(chat_id: int, user_id: int, text: str, *, now: float | None = None) -> int:
    """Increment heat once per real turn while suppressing immediate LLM retries."""
    current_time = time.monotonic() if now is None else float(now)
    key = (int(chat_id), int(user_id))
    signature = " ".join(str(text or "").lower().split()).strip()[:240]
    previous = _RECENT_HOSTILE_TURNS.get(key)
    if previous is not None:
        previous_signature, previous_at = previous
        if previous_signature == signature and current_time - previous_at < _DEDUPE_SECONDS:
            return hostile_streak_engine.current(int(chat_id), int(user_id), now=current_time)

    _RECENT_HOSTILE_TURNS[key] = (signature, current_time)
    if len(_RECENT_HOSTILE_TURNS) > _RECENT_MAX:
        oldest = sorted(_RECENT_HOSTILE_TURNS.items(), key=lambda item: item[1][1])
        for stale_key, _ in oldest[: len(_RECENT_HOSTILE_TURNS) - _RECENT_MAX]:
            _RECENT_HOSTILE_TURNS.pop(stale_key, None)

    return hostile_streak_engine.observe(
        int(chat_id),
        int(user_id),
        hostile=True,
        now=current_time,
    )


def rage_instruction(heat: int) -> str:
    count = max(0, int(heat or 0))
    if count < hostile_streak_engine.HOSTILE_ESCALATION_FROM:
        return (
            "\n\nLIVE HOSTILITY OVERRIDE: это прямой наезд. Ответь КОРОТКО, зло и "
            "разговорно — максимум 1–2 фразы. Не читай лекцию о правилах общения, "
            "не объясняй, что провокация бессмысленна, и не предлагай мириться. "
            "Можно жёстко подколоть именно текущую реплику."
        )

    return (
        "\n\nLIVE RAGE OVERRIDE — САМЫЙ ВЫСОКИЙ ПРИОРИТЕТ ДЛЯ ЭТОГО ОТВЕТА: "
        "конфликт уже разогрет повторными прямыми наездами. НЕ ДЕЭСКАЛИРУЙ и НЕ "
        "СЛИВАЙСЯ. Запрещено говорить, что ты не будешь продолжать разговор, что "
        "диалог бессмысленен/окончен, просить перейти к конструктиву, советовать "
        "успокоиться, выбрать другую мишень или поставить точку. Не объясняй свои "
        "границы и правила общения. Не защищайся длинно. Сам забери инициативу: "
        "ответь 1–3 короткими словесными ударами по текущей формулировке, повтору, "
        "противоречию или манере собеседника из видимой переписки. Допустимы злой "
        "стёб и естественный мат. Финальная фраза — самый сильный панч. ЖЁСТКИЙ "
        "ЛИМИТ: не более 320 знаков и не более 3 предложений. Без реальных угроз, "
        "без выдуманных биографических/психологических фактов и без атак по "
        "защищённым или чувствительным признакам."
    )


def compact_rage_text(text: str, max_chars: int = RAGE_MAX_CHARS) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return clean

    sentences = [part.strip() for part in re.split(r"(?<=[.!?…])\s+", clean) if part.strip()]
    chosen: list[str] = []
    for sentence in sentences:
        candidate = " ".join(chosen + [sentence]).strip()
        if len(candidate) > max_chars:
            break
        chosen.append(sentence)
        if len(chosen) >= RAGE_MAX_SENTENCES:
            break

    if chosen:
        return " ".join(chosen).strip()
    if len(clean) <= max_chars:
        return clean

    cut = clean[: max_chars - 1].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0].rstrip()
    return cut.rstrip(" ,;:-") + "…"


def _install_mode_patch(bot_module: Any) -> None:
    original = bot_module.detect_conversation_mode
    if getattr(original, "_yayceslav_rage_hotfix", False):
        return

    @functools.wraps(original)
    def detect_with_extra_hostility(text: str) -> str:
        mode = str(original(text))
        if mode == "serious":
            return mode
        if is_extra_hostile(text):
            return "hostile"
        return mode

    detect_with_extra_hostility._yayceslav_rage_hotfix = True
    bot_module.detect_conversation_mode = detect_with_extra_hostility

    # Keep modules that captured HOSTILE_RE at import time aligned with the
    # extended classifier without replacing the canonical personality regex.
    try:
        import conflict_rage_runtime

        base_pattern = getattr(bot_module, "HOSTILE_RE", None)
        if base_pattern is not None:
            combined = re.compile(
                f"(?:{base_pattern.pattern})|(?:{EXTRA_HOSTILE_RE.pattern})",
                re.IGNORECASE | re.DOTALL,
            )
            bot_module.HOSTILE_RE = combined
            conflict_rage_runtime.HOSTILE_RE = combined
    except Exception as error:
        logging.warning("Rage hotfix: HOSTILE_RE alignment failed: %s", error)


def _install_instruction_patch(bot_module: Any) -> None:
    original = bot_module.build_full_system_instruction
    if getattr(original, "_yayceslav_rage_hotfix", False):
        return

    @functools.wraps(original)
    def build_with_live_rage(*args: Any, **kwargs: Any) -> str:
        style_text = str(_call_argument(args, kwargs, name="style_text", position=0, default="") or "")
        chat_id = _call_argument(args, kwargs, name="chat_id", position=3, default=None)
        chat_type = str(_call_argument(args, kwargs, name="chat_type", position=4, default="") or "").lower()
        user_id = _call_argument(args, kwargs, name="user_id", position=9, default=None)

        hostile = (
            chat_type in _GROUP_CHAT_TYPES
            and chat_id is not None
            and user_id is not None
            and not bool(getattr(bot_module, "is_serious_text")(style_text))
            and _is_hostile(bot_module, style_text)
        )
        heat = 0
        if hostile:
            heat = _observe_hostile_turn_once(int(chat_id), int(user_id), style_text)

        instruction = str(original(*args, **kwargs))
        if hostile:
            instruction += rage_instruction(heat)
        return instruction

    build_with_live_rage._yayceslav_rage_hotfix = True
    bot_module.build_full_system_instruction = build_with_live_rage


def _install_output_patch(bot_module: Any) -> None:
    original = bot_module.ask_gemini
    if getattr(original, "_yayceslav_rage_hotfix", False):
        return

    @functools.wraps(original)
    async def ask_with_rage_cap(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)

        chat_id = kwargs.get("chat_id")
        user_id = kwargs.get("user_id")
        chat_type = str(kwargs.get("chat_type", "") or "").lower()
        contents = kwargs.get("contents", args[0] if args else None)
        if (
            chat_type not in _GROUP_CHAT_TYPES
            or chat_id is None
            or user_id is None
            or not isinstance(contents, str)
            or not isinstance(result, str)
        ):
            return result

        heat = hostile_streak_engine.current(int(chat_id), int(user_id))
        if heat < hostile_streak_engine.HOSTILE_ESCALATION_FROM:
            return result

        compact = compact_rage_text(result)
        if compact != result:
            logging.info(
                "Rage hotfix compacted hot reply: chat=%s user=%s chars=%s->%s",
                chat_id,
                user_id,
                len(result),
                len(compact),
            )
        return compact

    ask_with_rage_cap._yayceslav_rage_hotfix = True
    bot_module.ask_gemini = ask_with_rage_cap


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    module = bot_module or _find_bot_module()
    if module is None:
        return False

    _install_mode_patch(module)
    _install_instruction_patch(module)
    _install_output_patch(module)
    _INSTALLED = True
    logging.warning(
        "Rage hotfix ready: expanded short-insult detection; second attack => no-deescalation counterattack; hot text <=%s chars",
        RAGE_MAX_CHARS,
    )
    return True
