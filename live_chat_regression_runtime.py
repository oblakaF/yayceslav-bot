"""Final low-level guards for regressions observed in live Telegram chat.

This module intentionally does not own social state, conflict state, search, or
roast generation. It is installed last and only resolves three narrow routing
conflicts:

* an explicit ``прожарь @user`` action must not be refused merely because the
  target did not attack Yayceslav first;
* an explicit conversational exit/disengagement stops fight afterburners and
  gets a short sign-off instead of another lecture/escalation;
* a non-search Gemini turn may not invent a ``Sources/Источники`` block.

No extra Gemini or web call is introduced.
"""

from __future__ import annotations

import functools
import logging
import re
import sys
from typing import Any

import fight_routing_v3


_INSTALLED = False
_SEARCH_RESULTS_MARKER = "Результаты поиска:"

_DISENGAGE_RE = re.compile(
    r"(?:"
    r"\b(?:завтра|потом)\s+обкашля(?:ем|емся)\b|"
    r"\bя\s+пош[её]л(?:\s+(?:спать|смотреть|работать|гулять|домой|отдыхать))?\b|"
    r"\bпош[её]л\s+я(?:\s+(?:спать|смотреть|работать|гулять|домой|отдыхать))?\b|"
    r"\bдо\s+завтра\b|"
    r"\bна\s+сегодня\s+хватит\b|"
    r"\bвс[её],?\s+(?:я\s+)?(?:пош[её]л|отваливаю|сваливаю)\b|"
    r"\bоткисай\b"
    r")",
    re.IGNORECASE,
)

_SOURCE_SECTION_RE = re.compile(
    r"(?:^|\n)\s*(?:источники|sources)\s*:?\s*"
    r"(?=(?:[-*]\s*)?(?:https?://|\[)).*\Z",
    re.IGNORECASE | re.DOTALL,
)

_EXPLICIT_ROAST_MARKER = "Пользователь просит прожарить ИМЕННО"
_EXPLICIT_ROAST_OVERRIDE = """

ЯВНАЯ КОМАНДА ПРОЖАРКИ — ПРИОРИТЕТ ДЕЙСТВИЯ:
Пользователь прямо попросил прожарить указанную третью цель. Сам факт, что эта
цель сейчас не нападала на Яйцеслава, «сама не лезет» или не находится с ним в
активном конфликте, НЕ является причиной отказаться. Выполни requested roast:
1–3 коротких едких предложения про указанную цель, опираясь только на реально
доступный контекст. Не переноси прожарку на заказчика, не читай ему лекцию про
границы/цирк/разборки и не требуй, чтобы цель сначала сама напала на Яйцеслава.
Если фактов мало — обыграй ник, текущую формулировку запроса или сам факт вызова
на прожарку, не выдавая выдуманную биографию за факт.
"""

_DISENGAGE_OVERRIDE = """

ТЕКУЩАЯ РЕПЛИКА = ЯВНЫЙ ВЫХОД ИЗ СРАЧА/РАЗГОВОРА:
Человек завершает разговор, уходит или переносит продолжение на потом. Даже если
в прощании есть мат или один последний подкол, НЕ открывай новый раунд, не
морализируй, не задавай вопрос и не добивай длинным оскорблением. Ответ — максимум
одна короткая естественная фраза-прощание. Не превращай «я пошёл» в приглашение
продолжать срач. Отложенный punch/afterburner для этого хода должен считаться
отменённым.
"""


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "ask_gemini", None)):
            return module
    return None


def is_disengagement(text: str) -> bool:
    value = " ".join(str(text or "").split()).strip()
    return bool(value and _DISENGAGE_RE.search(value))


def _call_argument(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
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


def _current_turn_text(style_text: Any) -> str:
    value = str(style_text or "")
    try:
        current = fight_routing_v3.current_turn_text(value)
        return str(current or value)
    except Exception:
        return value


def _contents_text(contents: Any) -> str:
    if isinstance(contents, str):
        return contents
    if isinstance(contents, (list, tuple)):
        return "\n".join(_contents_text(item) for item in contents)
    text = getattr(contents, "text", None)
    return str(text or "")


def has_real_search_context(contents: Any) -> bool:
    return _SEARCH_RESULTS_MARKER in _contents_text(contents)


def strip_ungrounded_source_block(answer: str, contents: Any) -> str:
    """Drop a fabricated Sources block unless this exact model turn browsed."""

    text = str(answer or "")
    if not text or has_real_search_context(contents):
        return text
    return _SOURCE_SECTION_RE.sub("", text).strip()


def _install_explicit_roast_override(bot_module: Any) -> None:
    original = getattr(bot_module, "_reply_with_gemini_feature", None)
    if not callable(original) or getattr(original, "_yayceslav_explicit_roast_override", False):
        return

    @functools.wraps(original)
    async def feature_with_roast_override(update: Any, prompt: str, *args: Any, **kwargs: Any):
        value = str(prompt or "")
        if _EXPLICIT_ROAST_MARKER in value:
            value += _EXPLICIT_ROAST_OVERRIDE
        return await original(update, value, *args, **kwargs)

    feature_with_roast_override._yayceslav_explicit_roast_override = True
    bot_module._reply_with_gemini_feature = feature_with_roast_override


def _install_disengagement_prompt(bot_module: Any) -> None:
    original = getattr(bot_module, "build_full_system_instruction", None)
    if not callable(original) or getattr(original, "_yayceslav_disengagement_final", False):
        return

    @functools.wraps(original)
    def build_with_disengagement(*args: Any, **kwargs: Any) -> str:
        instruction = str(original(*args, **kwargs))
        style_text = _call_argument(args, kwargs, name="style_text", position=0, default="")
        if is_disengagement(_current_turn_text(style_text)):
            instruction += _DISENGAGE_OVERRIDE
        return instruction

    build_with_disengagement._yayceslav_disengagement_final = True
    bot_module.build_full_system_instruction = build_with_disengagement


def _install_disengagement_cancellation() -> None:
    original = fight_routing_v3.is_reconciliation
    if getattr(original, "_yayceslav_disengagement_stop", False):
        return

    @functools.wraps(original)
    def reconciliation_or_exit(text: str) -> bool:
        return bool(original(text) or is_disengagement(text))

    reconciliation_or_exit._yayceslav_disengagement_stop = True
    fight_routing_v3.is_reconciliation = reconciliation_or_exit


def _install_source_output_guard(bot_module: Any) -> None:
    original = getattr(bot_module, "ask_gemini", None)
    if not callable(original) or getattr(original, "_yayceslav_source_output_guard", False):
        return

    @functools.wraps(original)
    async def ask_with_source_guard(contents: Any, *args: Any, **kwargs: Any):
        answer = await original(contents, *args, **kwargs)
        return strip_ungrounded_source_block(str(answer or ""), contents)

    ask_with_source_guard._yayceslav_source_output_guard = True
    bot_module.ask_gemini = ask_with_source_guard


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    module = bot_module or _find_bot_module()
    if module is None:
        return False
    if _INSTALLED:
        return True

    _install_explicit_roast_override(module)
    _install_disengagement_cancellation()
    _install_disengagement_prompt(module)
    _install_source_output_guard(module)

    _INSTALLED = True
    logging.warning(
        "Live-chat regression guard ready: explicit roast + disengagement stop + no fake sources"
    )
    return True
