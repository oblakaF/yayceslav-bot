"""Shared group-banter continuity without a second social FSM.

This runtime addresses a live-chat failure mode where several members continue
one obviously absurd/improvised scene, but Yayceslav switches into literal
fact-checking or defensive conflict language instead of playing along.

It is intentionally stateless between messages: it only inspects the current
turn plus the already-bounded recent group context supplied to the normal system
prompt. It also narrows the legacy auto-search heuristic so a loose temporal
word cannot by itself turn playful narration into a web search.

One important routing exception lives here too: reported/narrated hostility from
a third party ("он шепчет, что ты будешь ...") is not a direct attack by the
sender. During that one build call we suppress conflict escalation, historical
hostility tone, fatigue, argumentative carry-over and proactive dokop. The same
semantic override is also visible to post-generation guards, so they cannot
reclassify the exact same narrated line as HOSTILE after the prompt was built.
"""

from __future__ import annotations

import contextvars
import functools
import logging
import re
import sys
from dataclasses import replace
from typing import Any

import aggression_engine
import passive_engine
import personality
import social_engine
import state_engine


_INSTALLED = False
_BANTER_SCOPE: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "yayceslav_shared_banter_scope",
    default=False,
)

_GENERIC_TEMPORAL_RE = re.compile(
    r"\b(?:сейчас|сегодня|на\s+данный\s+момент|прямо\s+сейчас)\b",
    re.IGNORECASE,
)
_EXPLICIT_WEB_RE = re.compile(
    r"\b(?:проверь|найди|поищи|глянь|посмотри|чекни|погугли|загугли)\b",
    re.IGNORECASE,
)
_STRONG_FRESHNESS_RE = re.compile(
    r"(?:"
    r"^\s*(?:кто|что|где|когда|сколько|какой|какая|какие|правда\s+ли)\b.{0,60}\b(?:сейчас|сегодня)\b|"
    r"^\s*(?:сейчас|сегодня)\b.{0,45}\b(?:кто|что|где|когда|сколько|какой|какая|какие)\b|"
    r"\b(?:последн\w*|свеж\w*|актуальн\w*)\s+(?:новост\w*|событ\w*|данн\w*|информац\w*)\b|"
    r"\b(?:курс|цена|котировк|погод|расписан|статус\s+рейса|действующ\w*\s+закон|правил\w*\s+въезда)\b|"
    r"\b(?:выбор\w*|голосован\w*)\b.{0,55}\b(?:когда|дата|число|сейчас|сегодня|сентябр\w*|этого\s+года|2026)\b|"
    r"\b(?:когда|дата|число|сейчас|сегодня)\b.{0,55}\b(?:выбор\w*|голосован\w*)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_THIRD_PARTY_RE = re.compile(
    r"\b(?:он|она|они|кто[- ]?то|один\s+из\s+них|одна\s+из\s+них|этот|эта|эти)\b",
    re.IGNORECASE,
)
_NARRATION_RE = re.compile(
    r"\b(?:"
    r"говор\w*|сказ\w*|ор[её]т|шепч\w*|бормоч\w*|крич\w*|"
    r"сто(?:ит|ят)|ид[её]т|ед[её]т|беж\w*|лез\w*|навис\w*|"
    r"лома\w*|выбива\w*|доста[её]\w*|трога\w*|держ\w*|"
    r"расст[её]гива\w*|подход\w*|заход\w*|пыта\w*"
    r")\b",
    re.IGNORECASE,
)
_BOT_TARGET_RE = re.compile(
    r"\b(?:ты|тебя|тебе|тобой|твой|твоя|твою|твои|будешь|у\s+тебя|над\s+тобой)\b",
    re.IGNORECASE,
)

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
- можно коротко подколоть конкретную повторяющуюся механику автора, но только по
  реально видимым репликам;
- НЕ используй «психика», «патологическая фиксация», «проекция», «скрытые/влажные
  фантазии» как объяснение поведения человека.

ВЫХОД ИЗ РАМКИ: только когда текущий пользователь явно переключился на
реальный факт/вопрос/проверку (например «а реально сколько платят?», «проверь
новости», «это правда?»). Тогда отвечай фактически и при необходимости используй
поиск. Само наличие слов «сейчас», «президент», «ТЦК», «война» и т.п. внутри
продолжающейся шутки НЕ является таким переключением.
"""

_CURRENT_NARRATED_BANTER_RULE = """

ТЕКУЩАЯ РЕПЛИКА — ПЕРЕСКАЗ/ПРОДОЛЖЕНИЕ СЦЕНЫ, А НЕ НАЕЗД АВТОРА:
Автор описывает, что делает/говорит третий персонаж в общем bit. Грубые слова
внутри этого пересказа НЕ принадлежат автору как прямое оскорбление Яйцеслава.
На ЭТОМ ходу старая репутация «хейтера», fatigue, annoyed/argumentative и
случайный dokop не дают разрешения нападать на автора: текущая игровая сцена
важнее накопленного раздражения.
Не отвечай автору «отъебись»/«пошёл нахуй»/«завали ебало», не называй его
интернет-бойцом/фантазёром и не защищайся. Прими сцену и добавь следующий
короткий комедийный ход изнутри неё.
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
    if _EXPLICIT_WEB_RE.search(value) or _STRONG_FRESHNESS_RE.search(value):
        return False
    return True


def is_reported_banter_hostility(text: str) -> bool:
    """Detect third-party narration that must not count as sender hostility.

    This is deliberately semantic and narrow: it requires a third-person actor,
    a narration/action verb and a reference to Yayceslav in the same turn. A
    direct insult such as ``ты долбоеб, нюхай хуй`` does not match.
    """
    value = " ".join(str(text or "").split()).strip()
    if not value:
        return False
    if _EXPLICIT_WEB_RE.search(value) or _STRONG_FRESHNESS_RE.search(value):
        return False
    return bool(
        _THIRD_PARTY_RE.search(value)
        and _NARRATION_RE.search(value)
        and _BOT_TARGET_RE.search(value)
    )


def _call_argument(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    name: str,
    position: int,
    default: Any = None,
) -> Any:
    if name in kwargs:
        return kwargs[name]
    if len(args) > position:
        return args[position]
    return default


def _wrap_mode_detector(owner: Any) -> None:
    """Keep reported third-party speech neutral in every downstream layer.

    The context-local scope still controls the broader tone suppressions below,
    but semantic sender-hostility is not context-dependent: ``он орёт, что ты``
    is a report even when a post-generation guard re-checks it after prompt
    construction has finished.
    """

    original = getattr(owner, "detect_conversation_mode", None)
    if not callable(original) or getattr(original, "_yayceslav_banter_mode_guard", False):
        return

    @functools.wraps(original)
    def detect_banter_safe(text: str) -> str:
        if is_reported_banter_hostility(text):
            return "normal"
        return str(original(text))

    detect_banter_safe._yayceslav_banter_mode_guard = True
    owner.detect_conversation_mode = detect_banter_safe


def _install_search_narrowing(module: Any) -> None:
    original = getattr(module, "should_auto_search", None)
    if not callable(original) or getattr(original, "_yayceslav_banter_search_guard", False):
        return

    @functools.wraps(original)
    def should_auto_search_banter_safe(text: str) -> bool:
        decision = bool(original(text))
        if decision and temporal_marker_alone_is_not_search(text):
            logging.info(
                "Auto-search suppressed: loose temporal marker inside conversational turn: %r",
                str(text)[:180],
            )
            return False
        return decision

    should_auto_search_banter_safe._yayceslav_banter_search_guard = True
    module.should_auto_search = should_auto_search_banter_safe


def _install_mode_override(module: Any) -> None:
    # bot.py owns the runtime detector used by state/humor/fight/post guards.
    _wrap_mode_detector(module)


def _install_personality_mode_override() -> None:
    # personality.build_v2_base_instruction resolves this global detector at
    # call time. Without this patch the base prompt could still say HOSTILE.
    _wrap_mode_detector(personality)


def _install_secondary_tone_guards() -> None:
    """Suppress independent aggression sources only inside narrated banter."""

    original_aggression = aggression_engine.decide_aggression
    if not getattr(original_aggression, "_yayceslav_banter_secondary_guard", False):
        @functools.wraps(original_aggression)
        def decide_aggression_banter_safe(*args: Any, **kwargs: Any):
            if _BANTER_SCOPE.get():
                return aggression_engine.AggressionDecision(reason="shared_banter")
            return original_aggression(*args, **kwargs)

        decide_aggression_banter_safe._yayceslav_banter_secondary_guard = True
        aggression_engine.decide_aggression = decide_aggression_banter_safe

    original_fatigue = passive_engine.note_bot_call_and_maybe_fatigue
    if not getattr(original_fatigue, "_yayceslav_banter_secondary_guard", False):
        @functools.wraps(original_fatigue)
        def fatigue_banter_safe(*args: Any, **kwargs: Any):
            if _BANTER_SCOPE.get():
                return passive_engine.FatigueDecision(reason="shared_banter")
            return original_fatigue(*args, **kwargs)

        fatigue_banter_safe._yayceslav_banter_secondary_guard = True
        passive_engine.note_bot_call_and_maybe_fatigue = fatigue_banter_safe

    original_state = state_engine.resolve_state
    if not getattr(original_state, "_yayceslav_banter_secondary_guard", False):
        @functools.wraps(original_state)
        def state_banter_safe(*args: Any, **kwargs: Any):
            resolved = original_state(*args, **kwargs)
            if _BANTER_SCOPE.get() and resolved in {
                state_engine.STATE_ANNOYED,
                state_engine.STATE_ARGUMENTATIVE,
                state_engine.STATE_HOSTILE_RESPONSE,
            }:
                return state_engine.STATE_NORMAL
            return resolved

        state_banter_safe._yayceslav_banter_secondary_guard = True
        state_engine.resolve_state = state_banter_safe

    original_social = social_engine.build_social_instruction
    if not getattr(original_social, "_yayceslav_banter_secondary_guard", False):
        @functools.wraps(original_social)
        def social_banter_safe(ctx: Any, *args: Any, **kwargs: Any):
            if _BANTER_SCOPE.get():
                try:
                    ctx = replace(
                        ctx,
                        hostility_today=0,
                        friendliness_label="Не хейтер",
                        penance_pending=False,
                        relapse_count_today=0,
                    )
                except Exception:
                    pass
            return original_social(ctx, *args, **kwargs)

        social_banter_safe._yayceslav_banter_secondary_guard = True
        social_engine.build_social_instruction = social_banter_safe

    # These late-installed modules add persistent relationship tone after the
    # base social engine. Sanitize only their negative-history contribution for
    # the narrated shared-bit turn; familiarity/positive history still exists.
    try:
        import reputation_runtime

        original_rep = reputation_runtime._reputation_instruction
        if not getattr(original_rep, "_yayceslav_banter_secondary_guard", False):
            @functools.wraps(original_rep)
            def reputation_banter_safe(score: int, *args: Any, **kwargs: Any) -> str:
                if _BANTER_SCOPE.get():
                    return (
                        "\n\nLIFETIME REPUTATION LAYER — SHARED BANTER OVERRIDE:\n"
                        "Старая репутация остаётся памятью отношений, но на этом ходе "
                        "не разрешает нападать первым: автор продолжает общий прикол."
                    )
                return original_rep(score, *args, **kwargs)

            reputation_banter_safe._yayceslav_banter_secondary_guard = True
            reputation_runtime._reputation_instruction = reputation_banter_safe
    except Exception:
        logging.debug("Shared banter: reputation override unavailable", exc_info=True)

    try:
        import social_priority_runtime

        original_priority = social_priority_runtime.build_priority_instruction
        if not getattr(original_priority, "_yayceslav_banter_secondary_guard", False):
            @functools.wraps(original_priority)
            def priority_banter_safe(snapshot: Any, *args: Any, **kwargs: Any) -> str:
                if _BANTER_SCOPE.get():
                    try:
                        snapshot = replace(
                            snapshot,
                            reputation_score=max(0, int(snapshot.reputation_score)),
                            hostility_today=0,
                            insults_to_bot=0,
                            reputation_negative_events=0,
                        )
                    except Exception:
                        pass
                    kwargs["current_mode"] = "normal"
                    kwargs["serious_topic"] = False
                return original_priority(snapshot, *args, **kwargs)

            priority_banter_safe._yayceslav_banter_secondary_guard = True
            social_priority_runtime.build_priority_instruction = priority_banter_safe
    except Exception:
        logging.debug("Shared banter: priority override unavailable", exc_info=True)


def _install_prompt_rule(module: Any) -> None:
    original = getattr(module, "build_full_system_instruction", None)
    if not callable(original) or getattr(original, "_yayceslav_shared_banter", False):
        return

    @functools.wraps(original)
    def build_with_shared_banter(*args: Any, **kwargs: Any) -> str:
        style_text = str(_call_argument(args, kwargs, "style_text", 0, "") or "")
        chat_id = _call_argument(args, kwargs, "chat_id", 3, None)
        chat_type = str(_call_argument(args, kwargs, "chat_type", 4, "") or "").lower()
        user_id = _call_argument(args, kwargs, "user_id", 9, None)
        narrated = chat_type in ("group", "supergroup") and is_reported_banter_hostility(style_text)

        token = _BANTER_SCOPE.set(narrated)
        try:
            if narrated and chat_id is not None and user_id is not None:
                # False hostile heat from narrated third-party speech must not
                # keep the conflict FSM in WARNING/RAGE for the current line.
                try:
                    import hostile_streak_engine

                    hostile_streak_engine.reset(int(chat_id), int(user_id))
                except Exception:
                    logging.exception("Shared banter: failed to clear false conflict heat")
            instruction = str(original(*args, **kwargs))
        finally:
            _BANTER_SCOPE.reset(token)

        if chat_type in ("group", "supergroup"):
            instruction += _SHARED_BANTER_RULE
            if narrated:
                instruction += _CURRENT_NARRATED_BANTER_RULE
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
    _install_mode_override(module)
    _install_personality_mode_override()
    _install_secondary_tone_guards()
    _install_prompt_rule(module)
    module._yayceslav_shared_banter_installed = True
    _INSTALLED = True
    logging.warning(
        "Shared banter runtime ready: play-along priority + narrated-hostility conflict/base/post guard + secondary aggression suppression + loose-time auto-search guard"
    )
    return True
