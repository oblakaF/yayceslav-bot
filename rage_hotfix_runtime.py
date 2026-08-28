"""Final live-chat guard for compact, persistent active RAGE.

The core bot remains the single owner of hostile heat. This layer only:
- broadens direct-insult classification for phrases seen in Telegram;
- adds a highest-priority first-hit / second-hit behavior contract;
- hard-caps current hostile RAGE replies so they cannot become surrender essays.

No extra model calls, DB writes, workers or persistent memory are introduced.
"""

from __future__ import annotations

import functools
import logging
import re
import sys
from typing import Any, Mapping, Sequence

import hostile_streak_engine


_INSTALLED = False
_GROUP_CHAT_TYPES = {"group", "supergroup"}
RAGE_MAX_CHARS = 280
RAGE_MAX_SENTENCES = 3

# Not a generic profanity detector. These are direct attacks/provocations, while
# neutral swearing such as "бля, пробки заебали" must stay neutral toward bot.
EXTRA_HOSTILE_RE = re.compile(
    r"(?:"
    r"^\s*(?:"
    r"хуе?сос\w*|хуйсос\w*|"
    r"псин\w*|п[её]с(?:\s+еблив\w*)?|"
    r"ушл[её]п\w*|чучел\w*|обоссан\w*|ущерб\w*|"
    r"поплачь(?:\s+поплачь)?|слился(?:\s+маленьк\w*)?|"
    r"слабост\w*\s+обоссан\w*|"
    r"проебал\w*\s+слабост\w*\s+обоссан\w*|"
    r"нищ(?:ий|ая|ее|ие)\s+ху[йя]\w*|"
    r"психоз[ауы]?|рамсы\s+попутал\??|"
    r"нюхай\s+ху[йя]|ху[йя]\s+нюхай|"
    r"лох\w*|петух\w*|щегол\w*"
    r")[.!?,\s]*$|"
    r"\b(?:ты|тебя|тебе|твой|твоя|твои)\b.{0,28}\b(?:"
    r"хуе?сос\w*|хуйсос\w*|псин\w*|п[её]с\b|ушл[её]п\w*|чучел\w*|"
    r"обоссан\w*|ущерб\w*|лох\w*|петух\w*|щегол\w*"
    r")\b|"
    r"\b(?:хуе?сос\w*|хуйсос\w*|псин\w*|п[её]с\b|ушл[её]п\w*|чучел\w*|ущерб\w*)\b"
    r".{0,20}\b(?:ты|тебя|тебе)\b|"
    r"\b(?:твоя|твою|твоей)\s+(?:мам(?:а|ка|аша|у|ой)|мать)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_DEESCALATION_RE = re.compile(
    r"(?:"
    r"не\s+(?:собираюсь|буду|намерен)\s+(?:продолжать|участвовать|тратить)|"
    r"конструктивн\w+\s+диалог|не\s+вижу\s+смысла|"
    r"(?:общение|диалог|разговор)\s+(?:окончен|закончен|исчерпан)|"
    r"постав(?:им|ить)\s+точку|выбери\s+другую\s+мишень|"
    r"оставь\s+(?:мой\s+чат|мои\s+сообщения)\s+в\s+покое|"
    r"если\s+(?:есть|у\s+тебя\s+есть)\s+(?:внятн|реальн|конкретн)\w+\s+(?:вопрос|повод)|"
    r"без\s+(?:мата|оскорблений|провокаций)"
    r")",
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


def is_extra_hostile(text: str) -> bool:
    value = " ".join(str(text or "").split()).strip()
    return bool(value and EXTRA_HOSTILE_RE.search(value))


def _is_hostile(bot_module: Any, text: str) -> bool:
    value = str(text or "")
    if is_extra_hostile(value):
        return True
    pattern = getattr(bot_module, "HOSTILE_RE", None)
    try:
        return bool(pattern and pattern.search(value))
    except Exception:
        return False


def rage_instruction(heat: int) -> str:
    count = max(0, int(heat or 0))
    if count < hostile_streak_engine.HOSTILE_ESCALATION_FROM:
        return (
            "\n\nLIVE HOSTILITY OVERRIDE: это ПЕРВЫЙ прямой наезд. Не взрывайся сразу. "
            "Ответь короткой спокойной осадкой/предупреждением — максимум 1–2 фразы. "
            "Смысл уровня «полегче». Без дружелюбного сюсюканья, лекций, оправданий "
            "и просьб перейти к конструктиву. Второй прямой выпад включает RAGE."
        )

    return (
        "\n\nLIVE RAGE OVERRIDE — САМЫЙ ВЫСОКИЙ ПРИОРИТЕТ. Это ВТОРОЙ ИЛИ "
        "ПОСЛЕДУЮЩИЙ прямой наезд: Яйцеслав ВЗРЫВАЕТСЯ и забирает инициативу. "
        "Пока человек продолжает конфликт, НЕ ДЕЭСКАЛИРУЙ, НЕ СЛИВАЙСЯ, НЕ "
        "ПРОЯВЛЯЙ ДРУЖЕЛЮБИЕ И ЖАЛОСТЬ. Не объявляй разговор оконченным, не говори "
        "«не буду продолжать», «это бессмысленно», «давай конструктивно», «успокойся», "
        "«я выше этого». Не объясняй границы и не читай мораль. Ответ — 1–3 коротких "
        "злых удара. Бей по реально видимому контексту: повтору, противоречию, дешёвой "
        "провокации, неудачной формулировке или уже проявившемуся паттерну поведения. "
        "Если сообщений достаточно, можно язвительно разбирать стиль поведения человека "
        "по его собственным репликам: зацикленность, жажду последнего слова, повтор одной "
        "провокации, показную браваду и т.п. Не выдумывай биографические факты. Разрешены "
        "грубые метафоры, естественный мат, уничижительный бытовой стёб, сексуально-"
        "отношенческие панчи без утверждений о реальной интимной жизни и ЯВНО ШУТОЧНЫЕ "
        "псевдодиагнозы вроде «хронический синдром последнего слова». Реальный медицинский "
        "или психиатрический диагноз не выдавай за факт. По уровню допустимы свежие атаки "
        "в духе «ты чё, пёс, охуел» или «я не твоя бывшая, но даже из жалости твой цирк "
        "терпеть бы не стал» — примеры не копируй, генерируй по ситуации. Финальная фраза "
        "самая сильная; последнее слово остаётся за Яйцеславом, пока оппонент продолжает. "
        "ЖЁСТКИЙ ЛИМИТ: <=280 знаков и <=3 предложений. Без реальных угроз расправой, "
        "преследования, доксинга и атак по защищённым признакам."
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

    compact = " ".join(chosen).strip() if chosen else clean
    if len(compact) <= max_chars:
        return compact
    cut = compact[: max_chars - 1].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0].rstrip()
    return cut.rstrip(" ,;:-") + "…"


def contains_deescalation(text: str) -> bool:
    return bool(_DEESCALATION_RE.search(str(text or "")))


def _latest_user_text(contents: Any) -> str:
    try:
        import primitive_compact_guard
        return primitive_compact_guard.latest_user_text(contents)
    except Exception:
        return str(contents or "") if isinstance(contents, str) else ""


def _install_mode_patch(bot_module: Any) -> None:
    original = bot_module.detect_conversation_mode
    if getattr(original, "_yayceslav_rage_hotfix", False):
        return

    @functools.wraps(original)
    def detect_with_extra_hostility(text: str) -> str:
        mode = str(original(text))
        if mode == "serious":
            return mode
        return "hostile" if is_extra_hostile(text) else mode

    detect_with_extra_hostility._yayceslav_rage_hotfix = True
    bot_module.detect_conversation_mode = detect_with_extra_hostility

    # conflict_rage_runtime imported HOSTILE_RE by value, so align it too.
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

        # Core builder owns observe(). Call it first so current() includes THIS
        # turn; never increment here or the first hit would become the second.
        instruction = str(original(*args, **kwargs))
        if hostile:
            heat = hostile_streak_engine.current(int(chat_id), int(user_id))
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
        if chat_type not in _GROUP_CHAT_TYPES or chat_id is None or user_id is None or not isinstance(result, str):
            return result
        if hostile_streak_engine.current(int(chat_id), int(user_id)) < hostile_streak_engine.HOSTILE_ESCALATION_FROM:
            return result

        # A neutral question during RAGE must still get its useful answer. Hard
        # cap only when the CURRENT user turn is itself hostile.
        if not _is_hostile(bot_module, _latest_user_text(contents)):
            return result

        compact = compact_rage_text(result)
        if contains_deescalation(compact):
            first = re.split(r"(?<=[.!?…])\s+", compact, maxsplit=1)[0].strip()
            compact = first or compact_rage_text(compact, 120)
        if compact != result:
            logging.info(
                "Rage hotfix compacted hostile reply: chat=%s user=%s chars=%s->%s",
                chat_id, user_id, len(result), len(compact),
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
        "Rage hotfix ready: broader direct-insult detection; canonical second hit => persistent compact RAGE; hostile hot text <=%s chars",
        RAGE_MAX_CHARS,
    )
    return True
