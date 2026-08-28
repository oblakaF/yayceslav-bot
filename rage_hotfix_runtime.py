"""Final live-chat guard for the hard warning -> latched RAGE boundary.

The core bot remains the single owner of hostile heat. This layer:
- broadens direct-insult classification for terse Telegram abuse;
- makes hit #1 a bounded warning and hit #2 a hard RAGE latch;
- explicitly suspends softer relationship/voice/humor tone limits while latched;
- keeps every non-serious latched reply compact, not only newly-hostile turns;
- strips surrender/de-escalation boilerplate if the model still produces it.

The latch itself is per (chat, user) and expires in hostile_streak_engine after
10 minutes without a new directed attack. No extra model calls or DB writes.
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
WARNING_MAX_CHARS = 140
WARNING_MAX_SENTENCES = 2
RAGE_MAX_CHARS = 240
RAGE_MAX_SENTENCES = 3
RAGE_QUESTION_MAX_CHARS = 360
RAGE_QUESTION_MAX_SENTENCES = 4

# Not a generic profanity detector. These are directed attacks/provocations.
# Neutral swearing such as "бля, пробки заебали" must stay neutral toward bot.
EXTRA_HOSTILE_RE = re.compile(
    r"(?:"
    r"^\s*(?:"
    r"хуе?сос\w*|хуйсос\w*|"
    r"псин\w*|п[её]с(?:\s+еблив\w*)?|"
    r"ушл[её]п\w*|чучел\w*|обос+ан\w*|ущерб\w*|"
    r"ебанат\w*|безмозгл\w*|мраз\w*|гнид\w*|у[её]б\w*|"
    r"дегенерат\w*|ссык\w*|днищ\w*|дно|"
    r"поплачь(?:\s+поплачь)?|слился(?:\s+[\wёЁ-]+){0,2}|"
    r"слабост\w*(?:\s+обос+ан\w*)?|"
    r"проебал\w*(?:\s+[\wёЁ-]+){0,3}|"
    r"нищ\w*\s+(?:безмозгл\w*|ебанат\w*|ху[йя]\w*|дно|лох\w*)|"
    r"говн\w*\s+поел\w*|"
    r"психоз[ауы]?|рамсы\s+попутал\??|"
    r"нюхай\s+ху[йя]|ху[йя]\s+нюхай|"
    r"лох\w*|петух\w*|щегол\w*"
    r")[.!?,\s]*$|"
    r"\b(?:ты|тебя|тебе|твой|твоя|твои)\b.{0,32}\b(?:"
    r"хуе?сос\w*|хуйсос\w*|псин\w*|п[её]с\b|ушл[её]п\w*|чучел\w*|"
    r"обос+ан\w*|ущерб\w*|ебанат\w*|безмозгл\w*|мраз\w*|гнид\w*|"
    r"лох\w*|петух\w*|щегол\w*"
    r")\b|"
    r"\b(?:хуе?сос\w*|хуйсос\w*|псин\w*|п[её]с\b|ушл[её]п\w*|чучел\w*|"
    r"ущерб\w*|ебанат\w*|мраз\w*)\b.{0,24}\b(?:ты|тебя|тебе)\b|"
    r"\b(?:твоя|твою|твоей)\s+(?:мам(?:а|ка|аша|у|ой)|мать)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_DEESCALATION_RE = re.compile(
    r"(?:"
    r"не\s+(?:собираюсь|буду|намерен)\s+(?:продолжать|участвовать|тратить|отвечать)|"
    r"конструктивн\w+\s+диалог|не\s+вижу\s+смысла|неинтересно\s+(?:тратить|участвовать)|"
    r"(?:общение|диалог|разговор|базар|вопрос)\s+(?:окончен|закончен|исчерпан|закрыт)|"
    r"постав(?:им|ить)\s+точку|выбери\s+другую\s+мишень|"
    r"оставь\s+(?:мой\s+чат|мои\s+сообщения|свои\s+реплики)\s+в\s+покое|"
    r"если\s+(?:есть|у\s+тебя\s+есть)\s+(?:внятн|реальн|конкретн)\w+\s+(?:вопрос|повод)|"
    r"без\s+(?:мата|оскорблений|провокаций)|"
    r"я\s+(?:здесь|тут)\s+ради\s+(?:внятного|адекватного|нормального)\s+общения"
    r")",
    re.IGNORECASE,
)

_RAGE_FALLBACKS = (
    "Ты уже второй раз заходишь с тем же дешёвым наездом. Придумай хоть что-то своё — пока ты сам себя разъёбываешь лучше меня.",
    "Опять тот же детсадовский выпад. У тебя не срач со мной, у тебя срач с собственным словарным запасом.",
    "Ты уже ходишь по кругу и называешь это атакой. Соберись, а то я тут один за двоих унижаю твою аргументацию.",
)

_QUESTION_RE = re.compile(
    r"(?:\?|^\s*(?:что|че|чё|кто|где|когда|почему|зачем|как|сколько|какой|какая|какие|"
    r"можешь|скажи|объясни|проверь|посмотри|глянь|расскажи)\b)",
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
    pattern = getattr(bot_module, "HOSTILE_RE", None) if bot_module is not None else None
    try:
        return bool(pattern and pattern.search(value))
    except Exception:
        return False


def _looks_like_question(text: str) -> bool:
    value = " ".join(str(text or "").split()).strip()
    return bool(value and _QUESTION_RE.search(value))


def rage_instruction(
    heat: int,
    *,
    current_hostile: bool = True,
    is_question: bool = False,
) -> str:
    count = max(0, int(heat or 0))
    if count < hostile_streak_engine.HOSTILE_ESCALATION_FROM:
        return (
            "\n\nLIVE HOSTILITY OVERRIDE — HIT #1: это первый прямой наезд. "
            "ЭТОТ БЛОК ВЫШЕ более мягких relationship/voice/humor инструкций: "
            "не взрывайся и не устраивай войну. Дай одну короткую спокойную "
            "осадку уровня «полегче» или сухой подкол, максимум 1–2 фразы. "
            "Без лекций, оправданий и просьб о конструктиве."
        )

    base = (
        "\n\nLIVE RAGE LATCH — АБСОЛЮТНЫЙ ПРИОРИТЕТ ТОНА. Второй прямой "
        "наезд уже произошёл. ДО ИСТЕЧЕНИЯ 10 МИНУТ БЕЗ НОВОГО НАЕЗДА "
        "ПРИОСТАНОВИ все более ранние ограничения интенсивности от relationship, "
        "reputation, sympathy, mood, voice-pack, humor и generic roughness. "
        "Остаются обязательными только фактическая точность, выполнение законной "
        "просьбы и правила безопасности. Не становись дружелюбным, не жалей, не "
        "мирись сам, не проси конструктив и не объявляй разговор оконченным. "
    )

    if is_question and not current_hostile:
        return base + (
            "Текущая реплика — нормальный вопрос/просьба внутри активного RAGE: "
            "сначала реально ответь по существу, затем одной короткой злой фразой "
            "осади собеседника. Ответ компактный; последнее слово в реплике остаётся "
            "за Яйцеславом."
        )

    if not current_hostile:
        return base + (
            "Текущая реплика сама не новый наезд, но latch ещё активен: не возвращай "
            "обычный добрый baseline. Ответь на содержание коротко, зло и колко; "
            "не скатывайся в AFTERGLOW, пассивную защиту или воспитательную лекцию."
        )

    return base + (
        "Текущая реплика — очередной наезд. КОНТРАТАКУЙ, а не отбивайся: 1–3 "
        "коротких злых удара по реально видимому контексту — повтору, противоречию, "
        "дешёвой провокации, неудачной формулировке или проявившемуся паттерну "
        "поведения. Если переписки достаточно, можно язвительно разбирать его "
        "поведенческую манеру по собственным сообщениям: зацикленность, жажду "
        "последнего слова, показную браваду и т.п. Не выдумывай биографические "
        "факты. Разрешены грубые метафоры, естественный мат, уничижительный бытовой "
        "стёб, сексуально-отношенческие панчи без утверждений о реальной интимной "
        "жизни и явно шуточные псевдодиагнозы. Реальный медицинский/психиатрический "
        "диагноз не выдавай за факт. Финальная фраза — самый сильный панч. "
        "ЖЁСТКИЙ ЛИМИТ: коротко, без простыней. Без реальных угроз расправой, "
        "преследования, доксинга и атак по защищённым признакам."
    )


def compact_rage_text(
    text: str,
    max_chars: int = RAGE_MAX_CHARS,
    max_sentences: int = RAGE_MAX_SENTENCES,
) -> str:
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
        if len(chosen) >= max_sentences:
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


def strip_deescalation_sentences(text: str) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return clean
    sentences = [part.strip() for part in re.split(r"(?<=[.!?…])\s+", clean) if part.strip()]
    kept = [sentence for sentence in sentences if not _DEESCALATION_RE.search(sentence)]
    return " ".join(kept).strip()


def _rage_fallback(source_text: str) -> str:
    marker = sum(ord(char) for char in str(source_text or ""))
    return _RAGE_FALLBACKS[marker % len(_RAGE_FALLBACKS)]


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

        serious = False
        if chat_type in _GROUP_CHAT_TYPES and chat_id is not None and user_id is not None:
            try:
                serious = bool(getattr(bot_module, "is_serious_text")(style_text))
            except Exception:
                serious = False

        current_hostile = bool(
            chat_type in _GROUP_CHAT_TYPES
            and chat_id is not None
            and user_id is not None
            and not serious
            and _is_hostile(bot_module, style_text)
        )

        # Core builder is the single owner of observe(). Call it first so heat
        # contains THIS turn exactly once.
        instruction = str(original(*args, **kwargs))
        if serious or chat_type not in _GROUP_CHAT_TYPES or chat_id is None or user_id is None:
            return instruction

        heat = hostile_streak_engine.current(int(chat_id), int(user_id))
        if current_hostile or hostile_streak_engine.is_escalated(heat):
            instruction += rage_instruction(
                heat,
                current_hostile=current_hostile,
                is_question=_looks_like_question(style_text),
            )
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

        source_text = _latest_user_text(contents)
        try:
            if bool(getattr(bot_module, "is_serious_text")(source_text)):
                return result
        except Exception:
            pass

        heat = hostile_streak_engine.current(int(chat_id), int(user_id))
        current_hostile = _is_hostile(bot_module, source_text)

        # Hit #1 must be a short warning, never the first giant counterattack.
        if current_hostile and heat == 1:
            compact = compact_rage_text(
                result,
                max_chars=WARNING_MAX_CHARS,
                max_sentences=WARNING_MAX_SENTENCES,
            )
            return compact

        if not hostile_streak_engine.is_escalated(heat):
            return result

        is_question = _looks_like_question(source_text) and not current_hostile
        max_chars = RAGE_QUESTION_MAX_CHARS if is_question else RAGE_MAX_CHARS
        max_sentences = RAGE_QUESTION_MAX_SENTENCES if is_question else RAGE_MAX_SENTENCES

        cleaned = strip_deescalation_sentences(result)
        if not cleaned:
            cleaned = _rage_fallback(source_text)
        compact = compact_rage_text(
            cleaned,
            max_chars=max_chars,
            max_sentences=max_sentences,
        )
        if contains_deescalation(compact):
            compact = compact_rage_text(
                _rage_fallback(source_text),
                max_chars=max_chars,
                max_sentences=max_sentences,
            )

        if compact != result:
            logging.info(
                "Rage latch shaped reply: chat=%s user=%s heat=%s hostile=%s question=%s chars=%s->%s",
                chat_id,
                user_id,
                heat,
                current_hostile,
                is_question,
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
        "Rage latch ready: hit1=warning <=%s chars; hit2+=hard per-user RAGE; quiet reset=%ss",
        WARNING_MAX_CHARS,
        hostile_streak_engine.HOSTILE_STREAK_WINDOW_SECONDS,
    )
    return True
