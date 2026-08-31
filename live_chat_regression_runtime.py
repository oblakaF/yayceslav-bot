"""Final low-level guards for regressions observed in live Telegram chat.

This module intentionally does not own social state, conflict state, search, or
roast generation.  It is installed last and only resolves three narrow routing
conflicts:

* an explicit ``прожарь @user`` action must not be refused merely because the
  target did not attack Yayceslav first;
* an explicit conversational exit/disengagement stops fight afterburners and
  gets a short sign-off instead of another lecture/escalation;
* a casual non-search answer may not invent a Sources/Источники section or URLs.

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

_DISENGAGE_RE = re.compile(
    r"(?:"
    r"\b(?:завтра|потом)\s+обкашля(?:ем|емcя)\b|"
    r"\b(?:я\s+)?пош[её]л\s+я?\s*(?:спать|смотреть|работать|гулять|домой|отдыхать)?\b|"
    r"\bя\s+пош[её]л\b|"
    r"\bдо\s+завтра\b|"
    r"\bна\s+сегодня\s+хватит\b|"
    r"\bвс[её],?\s+(?:я\s+)?(?:пош[её]л|отваливаю|сваливаю)\b|"
    r"\bоткисай\b"
    r")",
    re.IGNORECASE,
)

_SOURCE_HEADER_RE = re.compile(
    r"(?:^|\n)\s*(?:источники|sources)\s*:?\s*(?:\n|$).*\Z",
    re.IGNORECASE | re.DOTALL,
)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_PROOF_OR_WEB_RE = re.compile(
    r"(?:"
    r"\b(?:найди|поищи|проверь|посмотри|глянь|чекни|погугли|загугли)\b.{0,35}"
    r"\b(?:интернет|инет|сеть|онлайн|ссылк|источник)\w*\b|"
    r"\b(?:ссылк|источник)\w*\s+(?:дай|покажи|где|есть)\b|"
    r"\b(?:дай|покажи|где)\s+(?:ссылк|источник)\w*\b|"
    r"\bпруф\w*\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_EXPLICIT_ROAST_MARKER = "Пользователь просит прожарить ИМЕННО"
_EXPLICIT_ROAST_OVERRIDE = """

ЯВНАЯ КОМАНДА ПРОЖАРКИ — ПРИОРИТЕТ ДЕЙСТВИЯ:
Пользователь прямо попросил прожарить указанную третью цель. Сам факт, что эта
цель сейчас не нападала на Яйцеслава и «сама не лезет», НЕ является причиной
отказаться. Выполни именно requested roast: 1–3 коротких едких предложения про
указанную цель, опираясь только на реально доступный контекст. Не переноси
прожарку на заказчика, не читай ему лекцию про границы/цирк/разборки и не
выдумывай биографию цели. Если фактов мало — обыграй ник, текущую реплику или
сам факт вызова на прожарку, не выдавая выдумку за факт.
"""

_DISENGAGE_OVERRIDE = """

ТЕКУЩАЯ РЕПЛИКА = ЯВНЫЙ ВЫХОД ИЗ СРАЧА/РАЗГОВОРА:
Человек завершает разговор, уходит или переносит продолжение на потом. Даже если
в прощании есть мат или подкол, НЕ открывай новый раунд, не морализируй, не
задавай вопрос и не добивай длинным оскорблением. Ответ — максимум одна короткая
естественная фраза-прощание. Отложенный punch/afterburner для этого хода должен
считаться отменённым.
"""


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "send_answer", None)):
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


def _replace_first_argument(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    name: str,
    value: Any,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    new_args = list(args)
    new_kwargs = dict(kwargs)
    if new_args:
        new_args[0] = value
    else:
        new_kwargs[name] = value
    return tuple(new_args), new_kwargs


def _source_text_from_send(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    # send_answer(update, context, text, force_voice=False, source_user_text="")
    if "source_user_text" in kwargs:
        return str(kwargs.get("source_user_text") or "")
    if len(args) >= 3:
        return str(args[2] or "")
    return ""


def _current_turn_text(style_text: Any) -> str:
    value = str(style_text or "")
    try:
        current = fight_routing_v3.current_turn_text(value)
        return str(current or value)
    except Exception:
        return value


def _should_preserve_sources(bot_module: Any, source_text: str) -> bool:
    text = str(source_text or "").strip()
    if not text:
        return False
    if _URL_RE.search(text) or _PROOF_OR_WEB_RE.search(text):
        return True

    extract = getattr(bot_module, "extract_search_query", None)
    try:
        if callable(extract) and extract(text) is not None:
            return True
    except Exception:
        pass

    about_bot = getattr(bot_module, "is_conversation_about_bot", None)
    auto_search = getattr(bot_module, "should_auto_search", None)
    try:
        if callable(auto_search):
            is_meta = bool(callable(about_bot) and about_bot(text))
            if not is_meta and bool(auto_search(text)):
                return True
    except Exception:
        pass
    return False


def strip_ungrounded_sources(answer: str, source_text: str, bot_module: Any) -> str:
    """Remove fabricated links/source blocks from a turn that did not browse."""

    text = str(answer or "")
    if not text or _should_preserve_sources(bot_module, source_text):
        return text

    text = _SOURCE_HEADER_RE.sub("", text).strip()
    lines = [line for line in text.splitlines() if not _URL_RE.search(line)]
    return "\n".join(lines).strip()


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
    original = getattr(bot_module, "send_answer", None)
    if not callable(original) or getattr(original, "_yayceslav_source_output_guard", False):
        return

    @functools.wraps(original)
    async def send_with_source_guard(update: Any, context: Any, text: Any, *args: Any, **kwargs: Any):
        source_text = _source_text_from_send(args, kwargs)
        clean = strip_ungrounded_sources(str(text or ""), source_text, bot_module)
        return await original(update, context, clean, *args, **kwargs)

    send_with_source_guard._yayceslav_source_output_guard = True
    bot_module.send_answer = send_with_source_guard


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
