"""Keep gratitude/praise out of Yayceslav's hostile or dismissive modes.

The legacy bot still owns the main Gemini call path, so this runtime installs a
small explicit guard at polling startup instead of editing bot.py. Pure praise
is classified as praise, cannot activate proactive aggression, and receives a
strong instruction to answer warmly/self-confidently rather than with a generic
"чё?"-style direct-ping response.
"""

from __future__ import annotations

import functools
import re
import sys


_PRAISE_RE = re.compile(
    r"(?:"
    r"\bспасибо\b|\bспс\b|\bблагодар\w*\b|"
    r"\b(?:мы\s+)?тебя\s+любим\b|\bлюблю\s+тебя\b|"
    r"\bобожаю\s+тебя\b|\bобожаем\s+тебя\b|"
    r"\bты\s+(?:лучший|красавчик|молодец)\b|"
    r"\bхорошая\s+работа\b|\bотлично\s+сделал\b"
    r")",
    re.IGNORECASE,
)

_FOLLOWUP_RE = re.compile(
    r"\?|\b(?:можешь|можете|найди|поищи|посмотри|проверь|сделай|"
    r"объясни|покажи|расскажи|скажи|помоги|а\s+как|а\s+что|"
    r"почему|зачем|где|когда|сколько)\b",
    re.IGNORECASE,
)

_PRAISE_INSTRUCTION = """

КРИТИЧЕСКОЕ ПРАВИЛО ДЛЯ ЭТОЙ РЕПЛИКИ:
Пользователь благодарит или хвалит Яйцеслава. Не агрись, не докапывайся,
не отвечай «чё?», «чего надо?» и не делай вид, что тебя раздражает похвала.
Ответь коротко, по-человечески и в характере: тепло, самодовольно или мемно.
Допустим тон вроде «Да ладно, я знаю, что хорош» / «Любовь принята» /
«Всегда пожалуйста», но не копируй один шаблон постоянно.
"""

_INSTALLED = False
_ORIGINAL_CLASSIFY = None


def is_pure_praise(text: str) -> bool:
    """True for praise/gratitude that is not also a follow-up request/question."""
    stripped = (text or "").strip()
    if not stripped or not _PRAISE_RE.search(stripped):
        return False
    return not bool(_FOLLOWUP_RE.search(stripped))


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "build_v2_base_instruction", None)):
            return module
    return None


def install() -> bool:
    """Install the praise guard once, after bot.py has finished defining globals."""
    global _INSTALLED, _ORIGINAL_CLASSIFY
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

    original_builder = bot_module.build_v2_base_instruction
    if not getattr(original_builder, "_yayceslav_praise_guard", False):
        @functools.wraps(original_builder)
        def build_with_praise(user_text="", *args, **kwargs):
            base = original_builder(user_text, *args, **kwargs)
            if is_pure_praise(str(user_text or "")):
                return str(base) + _PRAISE_INSTRUCTION
            return base

        build_with_praise._yayceslav_praise_guard = True
        bot_module.build_v2_base_instruction = build_with_praise

    _INSTALLED = True
    return True
