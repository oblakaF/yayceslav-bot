"""Keep gratitude/praise short and make self-appearance feedback supportive.

Pure praise is handled locally: no Gemini round-trip, no long answer, no
aggression. Self-appearance requests still use Gemini/vision when available,
but receive a narrow positive-feedback instruction and cannot enter dokop mode.
"""

from __future__ import annotations

import functools
import random
import re
import sys


_PRAISE_RE = re.compile(
    r"(?:"
    r"\bспасибо\b|\bспс\b|\bблагодар\w*\b|"
    r"\bуважух\w*\b|\bреспект\b|"
    r"\bмолодец\b|\bкрасав(?:а|чик)\b|"
    r"\bты\s+(?:лучший|молодец|красав(?:а|чик))\b|"
    r"\b(?:мы\s+)?тебя\s+любим\b|\bлюблю\s+тебя\b|"
    r"\bобожаю\s+тебя\b|\bобожаем\s+тебя\b|"
    r"\bхорошая\s+работа\b|\bотлично\s+сделал\b|"
    r"\bкруто\s+сделал\b|\bклассно\s+сделал\b"
    r")",
    re.IGNORECASE,
)

_FOLLOWUP_RE = re.compile(
    r"\?|\b(?:можешь|можете|найди|поищи|посмотри|проверь|сделай|"
    r"объясни|покажи|расскажи|скажи|помоги|а\s+как|а\s+что|"
    r"почему|зачем|где|когда|сколько)\b",
    re.IGNORECASE,
)

_SELF_APPEARANCE_RE = re.compile(
    r"(?:"
    r"\bкак\s+(?:я\s+)?выгляжу\b|"
    r"\b(?:норм|нормально|хорошо)\s+(?:я\s+)?выгляжу\b|"
    r"\bкак\s+тебе\s+(?:мой|моя|мо[её])\s+(?:образ|лук|внешност\w*|фот\w*)\b|"
    r"\bмне\s+(?:это\s+)?ид[её]т\b|"
    r"\bоцени(?:шь|те)?\s+(?:мой|моя|мо[её])?\s*(?:образ|лук|внешност\w*|фот\w*)\b|"
    r"\bя\s+(?:красив(?:ый|ая)|симпатичн(?:ый|ая))\s*\?"
    r")",
    re.IGNORECASE,
)

SHORT_PRAISE_REPLIES = (
    "Спс.",
    "Класс.",
    "Я ценю.",
    "Уважуха.",
    "Любовь принята.",
    "Красавцы.",
)

_SELF_APPEARANCE_INSTRUCTION = """

КРИТИЧЕСКОЕ ПРАВИЛО ДЛЯ ЭТОГО ОТВЕТА:
Пользователь сам просит оценить свою внешность, фото или образ. Не агрись,
не подкалывай внешность и не ищи недостатки. Если изображение доступно,
ответь позитивно и коротко: сначала общая добрая оценка, затем 1–2 конкретных
видимых плюса — например стиль/одежда, причёска, выражение лица, поза, свет
или композиция. Не ставь унизительных оценок и не делай выводов о возрасте,
происхождении, здоровье, сексуальности, характере или других чувствительных
признаках. Обычно 1–3 коротких предложения. Если изображения нет или человека
на нём не видно, не выдумывай внешность — попроси прислать фото.
"""

_INSTALLED = False
_ORIGINAL_CLASSIFY = None
_ORIGINAL_ASK_GEMINI = None
_ORIGINAL_BUILD_V2 = None


def is_pure_praise(text: str) -> bool:
    """True for praise/gratitude that is not also a follow-up request/question."""
    stripped = (text or "").strip()
    if not stripped or not _PRAISE_RE.search(stripped):
        return False
    return not bool(_FOLLOWUP_RE.search(stripped))


def is_self_appearance_request(text: str) -> bool:
    """Recognize first-person requests for appearance/outfit/photo feedback."""
    return bool(_SELF_APPEARANCE_RE.search((text or "").strip()))


def choose_short_praise_reply(rng=None) -> str:
    chooser = rng or random
    return chooser.choice(SHORT_PRAISE_REPLIES)


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if (
            module is not None
            and callable(getattr(module, "build_v2_base_instruction", None))
            and callable(getattr(module, "ask_gemini", None))
        ):
            return module
    return None


def install() -> bool:
    """Install praise + self-appearance guards once after bot.py is ready."""
    global _INSTALLED, _ORIGINAL_CLASSIFY, _ORIGINAL_ASK_GEMINI, _ORIGINAL_BUILD_V2
    if _INSTALLED:
        return True

    import aggression_engine
    import intent

    if _ORIGINAL_CLASSIFY is None:
        _ORIGINAL_CLASSIFY = intent.classify_intent

    original_classify = _ORIGINAL_CLASSIFY
    if not getattr(intent.classify_intent, "_yayceslav_praise_guard", False):
        @functools.wraps(original_classify)
        def classify_with_praise(text, *args, **kwargs):
            value = str(text or "")
            if is_self_appearance_request(value):
                # A request is already excluded from proactive aggression.
                return "request", intent.HIGH
            if is_pure_praise(value):
                return "praise", intent.HIGH
            return original_classify(text, *args, **kwargs)

        classify_with_praise._yayceslav_praise_guard = True
        intent.classify_intent = classify_with_praise

    # Praise is never a valid reason for proactive dokop/aggression.
    aggression_engine._DOKOP_BLOCKED_INTENTS.add("praise")

    bot_module = _find_bot_module()
    if bot_module is None:
        return False

    # Add a narrow supportive instruction while preserving the real vision path.
    if _ORIGINAL_BUILD_V2 is None:
        _ORIGINAL_BUILD_V2 = bot_module.build_v2_base_instruction

    original_build_v2 = _ORIGINAL_BUILD_V2
    if not getattr(bot_module.build_v2_base_instruction, "_yayceslav_appearance_guard", False):
        @functools.wraps(original_build_v2)
        def build_v2_with_appearance(user_text="", *args, **kwargs):
            base = original_build_v2(user_text, *args, **kwargs)
            if is_self_appearance_request(str(user_text or "")):
                return str(base) + _SELF_APPEARANCE_INSTRUCTION
            return base

        build_v2_with_appearance._yayceslav_appearance_guard = True
        bot_module.build_v2_base_instruction = build_v2_with_appearance

    # Pure praise should not spend a Gemini call or produce a paragraph.
    if _ORIGINAL_ASK_GEMINI is None:
        _ORIGINAL_ASK_GEMINI = bot_module.ask_gemini

    original_ask_gemini = _ORIGINAL_ASK_GEMINI
    if not getattr(bot_module.ask_gemini, "_yayceslav_short_praise", False):
        @functools.wraps(original_ask_gemini)
        async def ask_gemini_with_short_praise(*args, **kwargs):
            contents = kwargs.get("contents", args[0] if args else "")
            try:
                import thinking_engine
                current_text = thinking_engine.latest_user_text(contents)
            except Exception:
                current_text = str(contents or "")

            if is_pure_praise(current_text):
                return choose_short_praise_reply()
            return await original_ask_gemini(*args, **kwargs)

        ask_gemini_with_short_praise._yayceslav_short_praise = True
        bot_module.ask_gemini = ask_gemini_with_short_praise

    _INSTALLED = True
    return True
