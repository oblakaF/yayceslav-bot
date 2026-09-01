"""Shared group-banter continuity without a second social FSM.

This runtime addresses a live-chat failure mode where several members continue
one obviously absurd/improvised scene, but Yayceslav switches into literal
fact-checking or defensive conflict language instead of playing along.

It is intentionally stateless: it only inspects the current turn plus the
already-bounded recent group context supplied to the normal system prompt.
It also narrows the legacy auto-search heuristic so the single temporal word
``сейчас`` cannot by itself turn playful narration into a web search.
"""

from __future__ import annotations

import functools
import logging
import re
import sys
from typing import Any


_INSTALLED = False

_GENERIC_TEMPORAL_RE = re.compile(
    r"\b(?:сейчас|сегодня|на\s+данный\s+момент|прямо\s+сейчас)\b",
    re.IGNORECASE,
)
_STRONG_FRESHNESS_RE = re.compile(
    r"(?:"
    r"\b(?:последн\w*|свеж\w*|актуальн\w*)\s+(?:новост\w*|событ\w*|данн\w*|информац\w*)\b|"
    r"\b(?:курс|цена|котировк|погод|расписан|статус\s+рейса|закон|правил\w*\s+въезда)\b|"
    r"\b(?:кто|что|где|когда|сколько|какой|какая|какие)\b.{0,30}\b(?:сейчас|сегодня)\b|"
    r"\b(?:сейчас|сегодня)\b.{0,30}\b(?:кто|что|где|когда|сколько|какой|какая|какие)\b|"
    r"\b(?:проверь|найди|поищи|глянь|посмотри|чекни|погугли|загугли)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_QUESTION_RE = re.compile(r"[?？]|\b(?:кто|что|где|когда|почему|зачем|сколько|какой|какая|какие|правда\s+ли)\b", re.IGNORECASE)

_SHARED_BANTER_RULE = """

SHARED BANTER FRAME — ПРИОРИТЕТ ЖИВОЙ ГРУППОВОЙ ИМПРОВИЗАЦИИ:
Посмотри на несколько последних реплик группы, а не только на буквальный смысл
текущей строки. Если два или больше участников продолжают одну очевидно
вымышленную/абсурдную сцену, шутливый сценарий или коллективный bit, и Яйцеслав
уже участвовал в этой сцене, считай её локальной реальностью ШУТКИ и продолжай
игру изнутри.

В таком shared-banter режиме:
- не становись фактчекером и не доказывай, что описанного «на самом деле нет»;
- не уходи в оборону фразами вроде «завязывай бредить», «цирк на пустом месте»,
  «угомонись», «хватит уже», если люди просто продолжают общий прикол;
- не объясняй участникам, что они фантазируют, и не диагностируй их психологию;
- лучше добавь следующий короткий комедийный ход, callback или переверни сцену;
- если к bit подключился второй/третий участник, это усиливает сигнал, что чат
  подыгрывает, а не атакует тебя;
- можно коротко подколоть конкретную повторяющуюся механику автора (например,
  что он уже ведёт покадровую трансляцию), но только по реально видимым репликам;
- НЕ используй «психика», «патологическая фиксация», «проекция», «скрытые/влажные
  фантазии» как объяснение поведения человека.

ВЫХОД ИЗ РАМКИ: только когда текущий пользователь явно переключился на
реальный факт/вопрос/проверку (например «а реально сколько платят?», «проверь
новости», «это правда?»). Тогда отвечай фактически и при необходимости используй
поиск. Само наличие слов «сейчас», «президент», «ТЦК», «война» и т.п. внутри
продолжающейся шутки НЕ является таким переключением.
"""


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "build_full_system_instruction", None)):
            return module
    return None


def temporal_marker_alone_is_not_search(text: str) -> bool:
    """True when legacy auto-search fired only because of a loose time word."""

    value = " ".join(str(text or "").split()).strip()
    if not value or not _GENERIC_TEMPORAL_RE.search(value):
        return False
    if _STRONG_FRESHNESS_RE.search(value):
        return False
    # A question mark by itself is not enough: "он сейчас дверь ломает, да?" is
    # still ordinary conversational narration. Require a factual interrogative.
    if _QUESTION_RE.search(value) and re.search(
        r"\b(?:кто|что|где|когда|почему|сколько|какой|какая|какие|правда\s+ли)\b",
        value,
        re.IGNORECASE,
    ):
        return False
    return True


def _install_search_narrowing(module: Any) -> None:
    original = getattr(module, "should_auto_search", None)
    if not callable(original) or getattr(original, "_yayceslav_banter_search_guard", False):
        return

    @functools.wraps(original)
    def should_auto_search_banter_safe(text: str) -> bool:
        decision = bool(original(text))
        if decision and temporal_marker_alone_is_not_search(text):
            logging.info("Auto-search suppressed: loose temporal marker inside conversational turn: %r", str(text)[:180])
            return False
        return decision

    should_auto_search_banter_safe._yayceslav_banter_search_guard = True
    module.should_auto_search = should_auto_search_banter_safe


def _install_prompt_rule(module: Any) -> None:
    original = getattr(module, "build_full_system_instruction", None)
    if not callable(original) or getattr(original, "_yayceslav_shared_banter", False):
        return

    @functools.wraps(original)
    def build_with_shared_banter(*args: Any, **kwargs: Any) -> str:
        instruction = str(original(*args, **kwargs))
        chat_type = kwargs.get("chat_type")
        if chat_type is None and len(args) > 4:
            chat_type = args[4]
        if str(chat_type or "").lower() in ("group", "supergroup"):
            instruction += _SHARED_BANTER_RULE
        return instruction

    build_with_shared_banter._yayceslav_shared_banter = True
    module.build_full_system_instruction = build_with_shared_banter


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    module = bot_module or _find_bot_module()
    if module is None:
        return False
    if _INSTALLED:
        return True

    _install_search_narrowing(module)
    _install_prompt_rule(module)
    module._yayceslav_shared_banter_installed = True
    _INSTALLED = True
    logging.warning("Shared banter runtime ready: play-along priority + loose-time auto-search guard")
    return True
