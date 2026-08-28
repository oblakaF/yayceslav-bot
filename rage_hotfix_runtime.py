"""Production guard for short-insult detection and compact active RAGE.

Live Telegram testing exposed two gaps that prompt wording alone did not fix:
1) many short Russian attacks were not classified as hostile, so the canonical
   streak never reached RAGE;
2) even in RAGE Gemini could produce long de-escalation/refusal lectures.

This runtime adds no model calls and no persistent storage. bot.py remains the
single owner of hostility counting; this layer only broadens classification,
adds the final high-priority RAGE instruction, and hard-caps hot hostile replies.
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

# Focused on direct abuse/provocation observed in real chat. This is not a
# generic profanity detector: "бля, пробки" must not become an attack on bot.
EXTRA_HOSTILE_RE = re.compile(
    r"(?:"
    r"^\s*(?:"
    r"хуе?сос\w*|хуйсос\w*|"
    r"псин\w*|п[её]с(?:\s+еблив\w*)?|"
    r"ушл[её]п\w*|чучел\w*|"
    r"обоссан\w*|ущерб\w*|"
    r"поплачь(?:\s+поплачь)?|"
    r"слился(?:\s+маленьк\w*)?|"
    r"слабост\w*\s+обоссан\w*|"
    r"нищ(?:ий|ая|ее|ие)\s+ху[йя]\w*|"
    r"психоз[ауы]?|"
    r"рамсы\s+попутал\??|"
    r"нюхай\s+ху[йя]|ху[йя]\s+нюхай|"
    r"лох\w*|петух\w*|щегол\w*"
    r")[.!?,\s]*$|"
    r"\b(?:ты|тебя|тебе|твой|твоя|твои)\b.{0,28}\b(?:"
    r"хуе?сос\w*|хуйсос\w*|псин\w*|п[её]с\b|ушл[её]п\w*|чучел\w*|обоссан\w*|"
    r"ущерб\w*|лох\w*|петух\w*|щегол\w*"
    r")\b|"
    r"\b(?:хуе?сос\w*|хуйсос\w*|псин\w*|п[её]с\b|ушл[её]п\w*|чучел\w*|ущерб\w*)\b.{0,20}\b(?:"
    r"ты|тебя|тебе"
    r")\b|"
    r"\b(?:твоя|твою|твоей)\s+(?:мам(?:а|ка|аша|у|ой)|мать)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_DEESCALATION_RE = re.compile(
    r"(?:"
    r"не\s+(?:собираюсь|буду|намерен)\s+(?:продолжать|участвовать|тратить)|"
    r"конструктивн\w+\s+диалог|"
    r"не\s+вижу\s+смысла|"
    r"(?:общение|диалог|разговор)\s+(?:окончен|закончен|исчерпан)|"
    r"постав(?:им|ить)\s+точку|"
    r"выбери\s+другую\s+мишень|"
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


def rage_instruction(heat: int) -> str:
    count = max(0, int(heat or 0))
    if count < hostile_streak_engine.HOSTILE_ESCALATION_FROM:
        return (
            "\n\nLIVE HOSTILITY OVERRIDE: это первый прямой наезд. Не взрывайся сразу. "
            "Ответь коротким предупреждением/осадкой — максимум 1–2 фразы, без "
            "дружелюбного сюсюканья и без лекции. Смысл: «полегче». Если человек "
            "продолжит наезжать, следующий прямой выпад переводит разговор в RAGE."
        )

    return (
        "\n\nLIVE RAGE OVERRIDE — САМЫЙ ВЫСОКИЙ ПРИОРИТЕТ: это уже второй или "
        "последующий прямой наезд. Яйцеслав ВЗРЫВАЕТСЯ и держит инициативу, пока "
        "оппонент продолжает конфликт. НЕ ДЕЭСКАЛИРУЙ, НЕ СЛИВАЙСЯ, НЕ ПРОСИ "
        "перейти к конструктиву и НЕ объявляй разговор оконченным. Не объясняй "
        "свои границы, не читай мораль, не жалей собеседника и не становись вежливее. "
        "Ответ — 1–3 коротких злых удара по тому, что реально видно в текущей реплике "
        "и недавнем контексте: его повтору, противоречию, дешёвой провокации, манере "
        "сраться или уже проявившемуся поведенческому паттерну. Если контекста накопилось "
        "достаточно, можно язвительно разбирать его стиль поведения по его же словам. "
        "Можно использовать грубый бытовой стёб, сексуально-отношенческие панчи без "
        "утверждений о реальной интимной жизни и ЯВНО ШУТОЧНЫЕ псевдодиагнозы вроде "
        "«синдром последнего слова» или «острая стадия интернет-героизма». Нельзя "
        "выдавать реальный медицинский/психиатрический диагноз за установленный факт. "
        "Допустимы естественный мат, очень злой стёб и уничижительный панч. По уровню "
        "допустимы свежие реплики в духе «ты чё, пёс, охуел», «я не твоя бывшая, но "
        "даже из жалости твой цирк терпеть бы не стал» — не копируй примеры механически, "
        "а бей по текущему контексту. Финальная фраза должна быть сильнейшей: последнее "
        "слово в этой реплике остаётся за Яйцеславом. ЖЁСТКИЙ ЛИМИТ: не более 280 знаков "
        "и не более 3 предложений. Без реальных угроз физической расправой, преследования, "
        "доксинга, выдуманной биографии и атак по защищённым признакам."
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
        if is_extra_hostile(text):
            return "hostile"
        return mode

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

        # The wrapped core builder is the single owner of observe(). Call it
        # first so current() below sees THIS turn. Never increment heat here.
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
        if (
            chat_type not in _GROUP_CHAT_TYPES
            or chat_id is None
            or user_id is None
            or not isinstance(result, str)
        ):
            return result

        heat = hostile_streak_engine.current(int(chat_id), int(user_id))
        if heat < hostile_streak_engine.HOSTILE_ESCALATION_FROM:
            return result

        # Preserve useful long answers to neutral questions asked during a hot
        # conflict. Hard-cap only a current hostile turn; answer-and-sting logic
        # remains free to answer substantive questions before the final jab.
        current_text = _latest_user_text(contents)
        if not _is_hostile(bot_module, current_text):
            return result

        compact = compact_rage_text(result)
        if contains_deescalation(compact):
            # Never replace with a canned insult. Keep only the first usable
            # sentence so a failed generation cannot turn into a surrender essay.
            first = re.split(r"(?<=[.!?…])\s+", compact, maxsplit=1)[0].strip()
            compact = first or compact_rage_text(compact, 120)

        if compact != result:
            logging.info(
                "Rage hotfix compacted hot hostile reply: chat=%s user=%s chars=%s->%s",
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
        "Rage hotfix ready: expanded direct-insult detection; canonical second attack => persistent compact RAGE; hostile hot text <=%s chars",
        RAGE_MAX_CHARS,
    )
    return True
