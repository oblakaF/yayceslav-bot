"""Explicit per-user conflict FSM for Yayceslav.

Design: code owns the state, Gemini only owns the wording.

NORMAL  -- first directed attack --> WARNING
WARNING -- second directed attack within 10 min --> RAGE
RAGE    -- 10 quiet minutes since last directed attack --> NORMAL

The state key is ``(chat_id, user_id)`` through the existing bounded
``hostile_streak_engine``.  We deliberately keep that engine as the only storage
and as the only counter owned by bot.py; this layer never double-increments text
turns.

The important architectural difference from the old conflict_rage +
rage_hotfix stack is prompt selection.  In RAGE we do NOT append another list of
"don't do X" rules to the normal personality.  We replace the normal social
prompt with one small active persona.  That prevents relationship, mood, humor
and de-escalation instructions from averaging the fight back into a polite
lecture.
"""

from __future__ import annotations

import functools
import json
import logging
import re
import sys
from enum import Enum
from typing import Any, Mapping, Sequence

import hostile_streak_engine


_INSTALLED = False
_GROUP_CHAT_TYPES = {"group", "supergroup"}

WARNING_MAX_CHARS = 140
WARNING_MAX_SENTENCES = 2
RAGE_MAX_CHARS = 220
RAGE_MAX_SENTENCES = 3
RAGE_QUESTION_MAX_CHARS = 420
RAGE_QUESTION_MAX_SENTENCES = 5


class ConflictPhase(str, Enum):
    NORMAL = "normal"
    WARNING = "warning"
    RAGE = "rage"


# Directed abuse seen in live Telegram tests.  This intentionally is not a
# generic profanity detector: "бля, пробки заебали" must not start a fight with
# the bot.  The canonical personality.HOSTILE_RE is checked as well.
EXTRA_HOSTILE_RE = re.compile(
    r"(?:"
    r"^\s*(?:"
    r"хуе?сос\w*|хуйсос\w*|псин\w*|п[её]с(?:\s+еблив\w*)?|"
    r"ишак\w*|дебил\w*|долбо[её]б\w*|ебанат\w*|безмозгл\w*|"
    r"ушл[её]п\w*|чучел\w*|обос+ан\w*|ущерб\w*|мраз\w*|гнид\w*|"
    r"у[её]б\w*|конч\w*|дегенерат\w*|ссык\w*|днищ\w*|дно|"
    r"поплачь(?:\s+поплачь)?|слился(?:\s+[\wёЁ-]+){0,2}|"
    r"слабост\w*(?:\s+обос+ан\w*)?|проебал\w*(?:\s+[\wёЁ-]+){0,3}|"
    r"нищ\w*(?:\s+(?:безмозгл\w*|ебанат\w*|ху[йя]\w*|дно|лох\w*)){1,3}|"
    r"говн\w*\s+поел\w*|психоз[ауы]?|рамсы\s+попутал\??|"
    r"нюхай\s+ху[йя]|ху[йя]\s+нюхай|иди\s+нахуй|пош[её]л\s+нахуй|"
    r"лох\w*|петух\w*|щегол\w*"
    r")[.!?,\s]*$|"
    r"\b(?:ты|тебя|тебе|твой|твоя|твои)\b.{0,36}\b(?:"
    r"хуе?сос\w*|хуйсос\w*|псин\w*|п[её]с\b|ишак\w*|дебил\w*|"
    r"долбо[её]б\w*|ушл[её]п\w*|чучел\w*|обос+ан\w*|ущерб\w*|"
    r"ебанат\w*|безмозгл\w*|мраз\w*|гнид\w*|конч\w*|лох\w*|петух\w*"
    r")\b|"
    r"\b(?:хуе?сос\w*|хуйсос\w*|псин\w*|п[её]с\b|ишак\w*|"
    r"дебил\w*|долбо[её]б\w*|ушл[её]п\w*|чучел\w*|ущерб\w*|"
    r"ебанат\w*|мраз\w*)\b.{0,28}\b(?:ты|тебя|тебе|бот)\b|"
    r"\b(?:твоя|твою|твоей)\s+(?:мам(?:а|ка|аша|у|ой)|мать)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_QUESTION_RE = re.compile(
    r"(?:\?|^\s*(?:что|че|чё|кто|где|когда|почему|зачем|как|сколько|"
    r"какой|какая|какие|можешь|скажи|объясни|проверь|посмотри|глянь|"
    r"расскажи|дай|найди|покажи)\b)",
    re.IGNORECASE,
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


def phase_from_heat(heat: int) -> ConflictPhase:
    count = max(0, int(heat or 0))
    if count >= hostile_streak_engine.HOSTILE_ESCALATION_FROM:
        return ConflictPhase.RAGE
    if count == 1:
        return ConflictPhase.WARNING
    return ConflictPhase.NORMAL


def phase(chat_id: int, user_id: int) -> ConflictPhase:
    return phase_from_heat(hostile_streak_engine.current(int(chat_id), int(user_id)))


def is_extra_hostile(text: str) -> bool:
    value = " ".join(str(text or "").split()).strip()
    return bool(value and EXTRA_HOSTILE_RE.search(value))


def is_direct_hostile(bot_module: Any, text: str) -> bool:
    value = str(text or "")
    if is_extra_hostile(value):
        return True
    pattern = getattr(bot_module, "HOSTILE_RE", None)
    try:
        return bool(pattern and pattern.search(value))
    except Exception:
        return False


def looks_like_question(text: str) -> bool:
    value = " ".join(str(text or "").split()).strip()
    return bool(value and _QUESTION_RE.search(value))


def observe_external_text(bot_module: Any, chat_id: int, user_id: int, text: str) -> int:
    """Observe a turn handled before bot.py's normal text/photo handler.

    Evidence-grounding handlers short-circuit the ordinary handler, so bot.py
    would otherwise never call hostile_streak_engine.observe for that turn.
    This function is for those short-circuited paths only.
    """

    hostile = is_direct_hostile(bot_module, text)
    return hostile_streak_engine.observe(
        int(chat_id),
        int(user_id),
        hostile=hostile,
    )


def _bounded_recent_context(recent_messages: Any, limit: int = 8) -> str:
    if not recent_messages:
        return ""
    try:
        items = list(recent_messages)[-limit:]
    except Exception:
        return ""

    lines: list[str] = []
    for item in items:
        clean = " ".join(str(item or "").split()).strip()
        if clean:
            lines.append(clean[:260])
    if not lines:
        return ""
    return "\n".join(lines)


def _current_date_line(bot_module: Any) -> str:
    try:
        now = bot_module.current_msk_datetime()
        return f"Текущая дата по МСК: {now:%Y-%m-%d}."
    except Exception:
        return ""


def build_warning_note() -> str:
    return (
        "\n\nCONFLICT FSM = WARNING. Это первый прямой наезд этого человека. "
        "Не начинай полноценный срач: ответь одной короткой спокойной осадкой "
        "или сухим подколом. Не пиши лекцию. Если он нападёт второй раз в "
        "10-минутном окне, код переведёт именно этого человека в RAGE."
    )


def build_rage_system_prompt(
    bot_module: Any,
    *,
    current_text: str,
    current_hostile: bool,
    user_name: str = "",
    recent_messages: Any = None,
) -> str:
    """Standalone persona used instead of the normal social prompt in RAGE."""

    question = looks_like_question(current_text) and not current_hostile
    date_line = _current_date_line(bot_module)
    context = _bounded_recent_context(recent_messages)
    name_line = f"Оппонент: {user_name}." if user_name else ""

    if question:
        task_line = (
            "Текущая реплика содержит реальный вопрос/просьбу. Сначала дай точный "
            "полезный ответ по существу. Если в запросе переданы результаты поиска, "
            "ссылка или содержимое страницы — они важнее твоих прошлых утверждений. "
            "После ответа добавь одну короткую злую колкость; финальная фраза твоя."
        )
    elif current_hostile:
        task_line = (
            "Текущая реплика — новый наезд. Сам забери инициативу. Выбери одну "
            "конкретную слабость текущей реплики или заметный паттерн из недавней "
            "переписки и разверни его против оппонента. Удар, затем добивание."
        )
    else:
        task_line = (
            "RAGE ещё активен, хотя текущая реплика не новый наезд. Ответь на её "
            "содержание без дружелюбного отката и закончи короткой колкой."
        )

    parts = [
        "Ты Яйцеслав. CONFLICT FSM = RAGE.",
        "Этот конкретный человек уже дважды прямо наехал на тебя за последние 10 минут.",
        "На время RAGE обычные relationship/mood/humor/roughness ограничения тона НЕ применяются.",
        "Ты злой, токсичный, инициативный и не обязан быть примирительным.",
        "Не объясняй свои границы и не превращай ответ в воспитательную речь.",
        "Не повторяй заготовку про словарный запас, если контекст даёт более точный панч.",
        "Используй реальные детали переписки: повторы, противоречия, браваду, нелепую формулировку, попытку выкрутиться.",
        "Можно естественный мат, грубые метафоры, уничижительный бытовой и сексуально-отношенческий стёб.",
        "Можно язвительно описывать наблюдаемую манеру поведения и шуточные псевдодиагнозы, но не выдавай реальный медицинский диагноз или выдуманную биографию за факт.",
        "Не угрожай физической расправой, не доксь и не атакуй защищённые признаки.",
        "Для обычного срача: 1–3 коротких предложения, без простыней; финальная фраза — самый сильный панч.",
        "Фактическая точность обязательна даже в RAGE. Если свежий факт неизвестен, не выдумывай его.",
        "Если в текущем запросе есть блок «Результаты поиска:», считай его свежим доказательством и отвечай только по нему; если он опровергает твой прошлый ответ — признай факт без оправданий.",
        task_line,
        date_line,
        name_line,
    ]
    if context:
        parts.extend((
            "Недавний контекст, который можно использовать для точного панча:",
            context,
        ))
    return "\n".join(part for part in parts if part)


def compact_text(text: str, *, max_chars: int, max_sentences: int) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return clean

    sentences = [part.strip() for part in re.split(r"(?<=[.!?…])\s+", clean) if part.strip()]
    selected: list[str] = []
    for sentence in sentences:
        candidate = " ".join(selected + [sentence]).strip()
        if len(candidate) > max_chars:
            break
        selected.append(sentence)
        if len(selected) >= max_sentences:
            break

    result = " ".join(selected).strip() if selected else clean
    if len(result) <= max_chars:
        return result

    cut = result[: max_chars - 1].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0].rstrip()
    return cut.rstrip(" ,;:-") + "…"


def _latest_user_text(contents: Any) -> str:
    try:
        import primitive_compact_guard
        return primitive_compact_guard.latest_user_text(contents)
    except Exception:
        if isinstance(contents, str):
            return contents
        if isinstance(contents, list):
            return " ".join(str(part) for part in contents if isinstance(part, str))
        return ""


def _install_mode_patch(bot_module: Any) -> None:
    original = bot_module.detect_conversation_mode
    if getattr(original, "_yayceslav_conflict_fsm", False):
        return

    @functools.wraps(original)
    def detect_with_direct_hostility(text: str) -> str:
        mode = str(original(text))
        if is_extra_hostile(text):
            return "hostile"
        return mode

    detect_with_direct_hostility._yayceslav_conflict_fsm = True
    bot_module.detect_conversation_mode = detect_with_direct_hostility

    # Keep the module-level regex consistent for code paths that use it directly.
    base_pattern = getattr(bot_module, "HOSTILE_RE", None)
    if base_pattern is not None:
        try:
            bot_module.HOSTILE_RE = re.compile(
                f"(?:{base_pattern.pattern})|(?:{EXTRA_HOSTILE_RE.pattern})",
                re.IGNORECASE | re.DOTALL,
            )
        except Exception:
            pass


def _install_instruction_router(bot_module: Any) -> None:
    original = bot_module.build_full_system_instruction
    if getattr(original, "_yayceslav_conflict_fsm", False):
        return

    @functools.wraps(original)
    def build_with_fsm(*args: Any, **kwargs: Any) -> str:
        style_text = str(_call_argument(args, kwargs, name="style_text", position=0, default="") or "")
        chat_id = _call_argument(args, kwargs, name="chat_id", position=3, default=None)
        chat_type = str(_call_argument(args, kwargs, name="chat_type", position=4, default="") or "").lower()
        user_name = str(_call_argument(args, kwargs, name="user_name", position=5, default="") or "")
        recent_messages = _call_argument(args, kwargs, name="recent_messages", position=6, default=None)
        user_id = _call_argument(args, kwargs, name="user_id", position=9, default=None)

        # Call the normal builder first. It owns the one-per-text-turn observe()
        # and all persistent social side effects. We may discard its prompt below,
        # but never its state transition.
        normal_instruction = str(original(*args, **kwargs))

        if chat_type not in _GROUP_CHAT_TYPES or chat_id is None or user_id is None:
            return normal_instruction

        current_phase = phase(int(chat_id), int(user_id))
        if current_phase is ConflictPhase.NORMAL:
            return normal_instruction

        current_hostile = is_direct_hostile(bot_module, style_text)
        if current_phase is ConflictPhase.WARNING:
            # Warning remains the ordinary personality plus one tiny note.
            return normal_instruction + build_warning_note()

        # RAGE is a separate persona, not "normal prompt + 15 blockers + rage".
        return build_rage_system_prompt(
            bot_module,
            current_text=style_text,
            current_hostile=current_hostile,
            user_name=user_name,
            recent_messages=recent_messages,
        )

    build_with_fsm._yayceslav_conflict_fsm = True
    bot_module.build_full_system_instruction = build_with_fsm


def _install_output_shape(bot_module: Any) -> None:
    original = bot_module.ask_gemini
    if getattr(original, "_yayceslav_conflict_fsm", False):
        return

    @functools.wraps(original)
    async def ask_with_fsm_shape(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        if not isinstance(result, str):
            return result

        chat_id = kwargs.get("chat_id")
        user_id = kwargs.get("user_id")
        chat_type = str(kwargs.get("chat_type", "") or "").lower()
        if chat_type not in _GROUP_CHAT_TYPES or chat_id is None or user_id is None:
            return result

        current_phase = phase(int(chat_id), int(user_id))
        if current_phase is ConflictPhase.NORMAL:
            return result

        contents = kwargs.get("contents", args[0] if args else None)
        source_text = _latest_user_text(contents)
        current_hostile = is_direct_hostile(bot_module, source_text)

        if current_phase is ConflictPhase.WARNING:
            if current_hostile:
                return compact_text(
                    result,
                    max_chars=WARNING_MAX_CHARS,
                    max_sentences=WARNING_MAX_SENTENCES,
                )
            return result

        # Do not chop real web-search answers: source URLs are appended after
        # generation and must remain intact. The standalone RAGE prompt already
        # asks the model to keep the prose concise.
        if isinstance(contents, str) and "Результаты поиска:" in contents:
            return result

        question = looks_like_question(source_text) and not current_hostile
        return compact_text(
            result,
            max_chars=RAGE_QUESTION_MAX_CHARS if question else RAGE_MAX_CHARS,
            max_sentences=RAGE_QUESTION_MAX_SENTENCES if question else RAGE_MAX_SENTENCES,
        )

    ask_with_fsm_shape._yayceslav_conflict_fsm = True
    bot_module.ask_gemini = ask_with_fsm_shape


def _install_voice_post_hook(bot_module: Any) -> None:
    """Share the same heat with addressed Voice 2.0 without another LLM call."""

    try:
        import voice2_runtime
    except Exception:
        return

    original = getattr(voice2_runtime, "_structured_voice_decision", None)
    if not callable(original) or getattr(original, "_yayceslav_conflict_fsm", False):
        return

    @functools.wraps(original)
    async def structured_with_fsm(module: Any, contents: Any, kwargs: dict[str, Any]) -> str:
        raw = await original(module, contents, kwargs)
        chat_id = kwargs.get("chat_id")
        user_id = kwargs.get("user_id")
        chat_type = str(kwargs.get("chat_type", "") or "").lower()
        if chat_type not in _GROUP_CHAT_TYPES or chat_id is None or user_id is None:
            return raw

        try:
            payload = json.loads(raw)
        except Exception:
            return raw
        transcript = " ".join(str(payload.get("transcript") or "").split()).strip()
        if not transcript:
            return raw

        if is_direct_hostile(bot_module, transcript):
            hostile_streak_engine.observe(int(chat_id), int(user_id), hostile=True)
        return raw

    structured_with_fsm._yayceslav_conflict_fsm = True
    voice2_runtime._structured_voice_decision = structured_with_fsm


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    module = bot_module or _find_bot_module()
    if module is None:
        return False

    _install_mode_patch(module)
    _install_instruction_router(module)
    _install_output_shape(module)
    _install_voice_post_hook(module)
    _INSTALLED = True
    logging.warning(
        "Conflict FSM ready: NORMAL -> WARNING -> RAGE; per-user quiet reset=%ss; RAGE uses standalone persona",
        hostile_streak_engine.HOSTILE_STREAK_WINDOW_SECONDS,
    )
    return True
