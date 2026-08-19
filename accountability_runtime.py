"""Make Yayceslav own real mistakes without apologizing on command.

A user correction is a reason to verify the previous answer, not a reason to
escalate. If the bot really was wrong, it should acknowledge that briefly and
immediately give the corrected answer. If the user's correction is itself
wrong, Yayceslav should explain calmly instead of producing a fake apology.
"""

from __future__ import annotations

import functools
import re
import sys


_CORRECTION_SIGNAL_RE = re.compile(
    r"(?:"
    r"\bты\s+(?:не\s+прав|неправ|ошиб\w+|был\s+не\s+прав)\b|"
    r"\bтвой\s+(?:ответ|факт|расч[её]т)\s+(?:невер\w*|неправиль\w*|ошибоч\w*)\b|"
    r"\bэто\s+(?:неверно|неправильно),?\s+(?:ты|яйцеслав)\b|"
    r"\bяйцеслав,?\s+(?:ты\s+)?(?:ошиб\w+|не\s+прав)\b|"
    r"\bпроверь\s+(?:свой|предыдущий)\s+ответ\b"
    r")",
    re.IGNORECASE,
)

_ACCOUNTABILITY_INSTRUCTION = """

ПРАВИЛО ОТВЕТСТВЕННОСТИ ЗА ОШИБКУ:
Пользователь указывает, что предыдущий ответ Яйцеслава может быть неверным.
Сначала сопоставь это с доступным контекстом и фактами. Не защищай прошлый
ответ из упрямства и не переходи в агрессию.
- Если Яйцеслав действительно ошибся: признай это коротко одной фразой
  («Моя ошибка.», «Да, тут я ошибся. Сорян.», «Ты прав, я затупил.»), затем
  сразу дай исправленный ответ. Не пиши длинное покаянное сообщение.
- Если пользователь сам ошибается: НЕ извиняйся автоматически; спокойно и
  кратко объясни, почему прежний ответ остаётся верным.
- Если по текущему контексту нельзя уверенно проверить: скажи, что можешь
  ошибаться, и предложи/выполни проверку вместо уверенного спора.
"""

_INSTALLED = False


def is_correction_signal(text: str) -> bool:
    return bool(_CORRECTION_SIGNAL_RE.search(str(text or "")))


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(
            getattr(module, "build_full_system_instruction", None)
        ):
            return module
    return None


def install() -> bool:
    """Install once after dialogue_guard has composed the instruction builder."""
    global _INSTALLED
    if _INSTALLED:
        return True

    import aggression_engine

    # A correction is a chance to verify ourselves, never a reason for an
    # initiative dokop. The old engine explicitly treated correction as
    # eligible; blocked intents take precedence in _base_probability().
    aggression_engine._DOKOP_BLOCKED_INTENTS.add("correction")

    bot_module = _find_bot_module()
    if bot_module is None:
        return False

    original = bot_module.build_full_system_instruction
    if not getattr(original, "_yayceslav_accountability", False):
        @functools.wraps(original)
        def build_with_accountability(*args, **kwargs):
            instruction = original(*args, **kwargs)
            style_text = args[0] if args else kwargs.get("style_text", "")
            if is_correction_signal(str(style_text or "")):
                return str(instruction) + _ACCOUNTABILITY_INSTRUCTION
            return instruction

        build_with_accountability._yayceslav_accountability = True
        bot_module.build_full_system_instruction = build_with_accountability

    _INSTALLED = True
    return True
