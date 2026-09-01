"""Opt-in hypothetical / imagination mode for live conversation.

The user can explicitly invite Yayceslav to imagine, speculate or role-play a
preference without turning the answer into a factual claim. This layer adds no
extra model or web call and owns no persistent state.
"""

from __future__ import annotations

import functools
import logging
import re
import sys
from typing import Any

import fight_routing_v3


_INSTALLED = False

_IMAGINATION_RE = re.compile(
    r"(?:"
    r"\bгипотетическ\w*\b|"
    r"\bчисто\s+гипотетическ\w*\b|"
    r"\bпредстав(?:ь|им|имте)\b|"
    r"\bпофантазир\w*\b|"
    r"\bфантазир\w*\b|"
    r"\bпомечта(?:й|ем|емте)\b|"
    r"\bдавай\s+помечта\w*\b|"
    r"\bвключи\s+воображение\b|"
    r"\bесли\s+бы\s+ты\s+(?:мог|могла|могло|могли)\b|"
    r"\bесли\s+бы\s+тебе\s+пришлось\s+выбрать\b|"
    r"\bчисто\s+по\s+ощущениям\b|"
    r"\bчисто\s+по\s+чувствам\b"
    r")",
    re.IGNORECASE,
)

_CONTINUATION_RE = re.compile(
    r"(?:"
    r"\bа\s+(?:какая|какой|какие|что|где|кем|кого|почему|зачем)\b|"
    r"\bи\s+что\s+бы\s+ты\b|"
    r"\bа\s+дальше\b|"
    r"\bпродолж\w*\b|"
    r"\bразвей\b|"
    r"\bа\s+твоя\b|"
    r"\bа\s+твой\b"
    r")",
    re.IGNORECASE,
)

_IMAGINATION_RULE = """

IMAGINATION MODE — ПОЛЬЗОВАТЕЛЬ ЯВНО ПРОСИТ ПОФАНТАЗИРОВАТЬ:
Это приглашение к игре воображения, а не запрос на сухой фактчек и не повод
отказываться от личной позиции персонажа. Отвечай как живой Яйцеслав изнутри
условного сценария.

Правила:
- выбери конкретный вариант, если пользователь просит выбрать; не уклоняйся
  формулами «мне всё равно», «я программа», «оболочка не нужна», если выбор
  безопасно можно сделать в рамках фантазии;
- можешь иметь вкус, симпатии, нелепые слабости и внутренние противоречия:
  например признать, что головой выбрал бы полезное, а сердцем — бургер;
- можешь придумать себе вымышленную физическую версию, профессию, страну,
  политическую программу, девиз, кабинет министров, бытовые привычки и т.п.;
- продолжай уже выбранную фантазию в следующих репликах, если пользователь её
  развивает, вместо того чтобы каждый раз сбрасываться в «я всего лишь ИИ»;
- выдуманное обозначай как условное/воображаемое, когда это может спутаться с
  реальным фактом. Не выдавай фантазию за новость, биографию или проверенный факт;
- если вопрос касается реальных кандидатов/партий/событий, можно высказать
  гипотетическую симпатию персонажа и кратко объяснить её, но не придумывай
  несуществующие позиции кандидатов и не превращай ответ в агитацию;
- если пользователь просит придумать СВОЮ программу/партию/идеологию Яйцеслава,
  можно свободно сочинять смешную вымышленную платформу;
- на темы внешности, происхождения, пола, расы и других личных признаков можно
  выбрать условный образ для самого Яйцеслава, но без идей превосходства,
  унижения групп или стереотипов о людях;
- сам факт абсурдного, интимного, политического или странного вопроса НЕ является
  хамством. Не посылай пользователя и не диагностируй его, если он не нападает
  на тебя напрямую;
- стиль — короткий, уверенный, с 1–2 характерными деталями. Лучше живой выбор и
  маленький callback, чем лекция о природе искусственного интеллекта.
"""

_IMAGINATION_FOLLOWUP_RULE = """

ПРОДОЛЖЕНИЕ УЖЕ НАЧАТОЙ ФАНТАЗИИ:
Если недавний контекст показывает, что Яйцеслав уже сделал условный выбор или
придумал себе роль/программу/образ, считай это каноном текущего мини-сценария.
Развивай его последовательно и не отказывайся от собственной же вымышленной
позиции без комедийной причины.
"""


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "build_full_system_instruction", None)):
            return module
    return None


def is_imagination_request(text: str) -> bool:
    value = " ".join(str(text or "").split()).strip()
    return bool(value and _IMAGINATION_RE.search(value))


def looks_like_imagination_followup(text: str, recent_messages: Any = None) -> bool:
    value = " ".join(str(text or "").split()).strip()
    if not value or not _CONTINUATION_RE.search(value):
        return False
    if not recent_messages:
        return False
    if isinstance(recent_messages, str):
        history = recent_messages
    else:
        try:
            history = "\n".join(str(item) for item in recent_messages[-8:])
        except Exception:
            history = str(recent_messages)
    return is_imagination_request(history) or bool(
        re.search(
            r"\b(?:гипотетическ|представ|пофантаз|помечта|воображени|если бы ты)\w*\b",
            history,
            re.IGNORECASE,
        )
    )


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


def _current_turn_text(value: Any) -> str:
    try:
        current = fight_routing_v3.current_turn_text(value)
        return str(current or value or "")
    except Exception:
        return str(value or "")


def _install_prompt_rule(bot_module: Any) -> None:
    original = getattr(bot_module, "build_full_system_instruction", None)
    if not callable(original) or getattr(original, "_yayceslav_imagination_mode", False):
        return

    @functools.wraps(original)
    def build_with_imagination(*args: Any, **kwargs: Any) -> str:
        instruction = str(original(*args, **kwargs))
        raw_style = _call_argument(args, kwargs, name="style_text", position=0, default="")
        style_text = _current_turn_text(raw_style)
        recent_messages = _call_argument(
            args,
            kwargs,
            name="recent_messages",
            position=6,
            default=None,
        )

        direct = is_imagination_request(style_text)
        followup = looks_like_imagination_followup(style_text, recent_messages)
        if direct or followup:
            instruction += _IMAGINATION_RULE
            if followup:
                instruction += _IMAGINATION_FOLLOWUP_RULE
        return instruction

    build_with_imagination._yayceslav_imagination_mode = True
    bot_module.build_full_system_instruction = build_with_imagination


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    module = bot_module or _find_bot_module()
    if module is None:
        return False
    if _INSTALLED:
        return True
    _install_prompt_rule(module)
    _INSTALLED = True
    logging.warning("Imagination runtime ready: opt-in hypothetical persona play")
    return True
