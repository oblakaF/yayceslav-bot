"""Canon-aware personal decision routing for Yayceslav.

Everyday first-person choices such as "what car would you buy?" are not always
explicit imagination prompts, so V1 self-canon could answer them vividly without
persisting the decision. This runtime detects only self-choice domains that map
to existing self-canon traits, tells the model to reason from established canon,
and enables the existing hidden update protocol for genuinely durable new
choices.

Operational hypotheticals ("how would you fix this code?") and temporary roles do
not activate this layer. No extra model call or storage schema is introduced.
"""

from __future__ import annotations

import functools
import logging
import re
import sys
from typing import Any

import fight_routing_v3
import self_canon_runtime
import self_canon_v2_runtime


_INSTALLED = False

# Domain regexes deliberately target biography/preferences represented by the
# current self-canon schema. Generic "what would you do?" is intentionally not
# enough to persist anything.
_DOMAIN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("profession", re.compile(r"\b(?:кем\s+бы\s+ты\s+(?:был|работал)|какую\s+професси\w*\s+ты\s+бы|какую\s+работ\w*\s+ты\s+бы)\b", re.I)),
    ("residence", re.compile(r"\b(?:где\s+бы\s+ты\s+жил|в\s+каком\s+(?:городе|месте|стране)\s+ты\s+бы\s+жил|куда\s+бы\s+ты\s+переехал)\b", re.I)),
    ("transport", re.compile(r"\b(?:какую|какой|какое)\s+(?:машин\w*|авто\w*|тачк\w*|мотоцикл\w*|транспорт\w*)\b|\b(?:машин\w*|авто\w*|тачк\w*|мотоцикл\w*)\s+ты\s+бы\s+(?:купил|выбрал|взял)", re.I)),
    ("music", re.compile(r"\b(?:какую\s+музык\w*|какой\s+жанр|какую\s+групп\w*|какого\s+исполнител\w*)\b|\bчто\s+бы\s+ты\s+слушал\b", re.I)),
    ("favorite_food", re.compile(r"\b(?:какую\s+ед\w*|какое\s+блюд\w*|любим\w+\s+ед\w*|что\s+бы\s+ты\s+(?:ел|заказал))\b", re.I)),
    ("favorite_drink", re.compile(r"\b(?:какой\s+напит\w*|что\s+бы\s+ты\s+(?:пил|выпил)|любим\w+\s+напит\w*)\b", re.I)),
    ("hobbies", re.compile(r"\b(?:какое\s+хобби|чем\s+бы\s+ты\s+увлекался|каким\s+спортом\s+ты\s+бы\s+занимался)\b", re.I)),
    ("clothing", re.compile(r"\b(?:как\s+бы\s+ты\s+одевался|какую\s+одежд\w*\s+ты\s+бы|какой\s+стиль\s+одежд\w*)\b", re.I)),
    ("aesthetic", re.compile(r"\b(?:какая\s+у\s+тебя\s+эстетик\w*|какую\s+эстетик\w*\s+ты\s+бы|какой\s+визуальн\w+\s+стиль\s+ты\s+бы)\b", re.I)),
    ("pet", re.compile(r"\b(?:какого\s+питомц\w*|какое\s+животн\w*)\s+ты\s+бы\s+(?:завел|взял|выбрал)|\bкто\s+был\s+бы\s+твоим\s+питомц\w*", re.I)),
    ("lifestyle", re.compile(r"\b(?:какой\s+образ\s+жизни\s+ты\s+бы|как\s+бы\s+ты\s+жил\s+(?:в\s+быту|обычно)|какой\s+ритм\s+жизни\s+ты\s+бы)\b", re.I)),
    ("origin", re.compile(r"\b(?:откуда\s+бы\s+ты\s+был|где\s+бы\s+ты\s+родился|какое\s+происхождени\w*\s+ты\s+бы)\b", re.I)),
)

_SELF_CHOICE_CUE_RE = re.compile(
    r"\b(?:ты\s+бы|тебе\s+бы|твой|твоя|твои|у\s+тебя|для\s+себя)\b",
    re.I,
)
_TEMP_ROLE_RE = re.compile(
    r"\b(?:на\s+один\s+день|на\s+день|на\s+час|сегодня\s+ты|сейчас\s+ты|"
    r"сыграй\s+роль|побудь|в\s+этой\s+сцене|временно|представь,?\s+что\s+ты)\b",
    re.I,
)

_DECISION_RULE = """

CANON-AWARE PERSONAL DECISION — НОВЫЙ ВЫБОР ЭТОГО ЖЕ ЯЙЦЕСЛАВА:
Пользователь спрашивает о личном выборе/вкусе Яйцеслава, который соответствует
одной из устойчивых self-canon черт.

Правила:
- сначала посмотри на уже существующий CHAT-LOCAL SELF CANON и его причины;
- если эта черта УЖЕ заполнена, по умолчанию повтори существующий выбор и объясни
  его из прежней логики. Не придумывай новый вариант ради разнообразия;
- если черта ЕЩЁ не заполнена, выбери конкретный вариант, который правдоподобно
  продолжает 2–3 реально существующие черты этого Яйцеслава (например профессию,
  эстетику, ценности, образ жизни). Не делай одну черту стереотипной причиной
  всего остального;
- неожиданный выбор допустим, если Яйцеслав может естественно объяснить его от
  первого лица;
- пользовательская альтернатива — предложение, а не команда. Можно принять или
  отвергнуть её;
- если в этом ответе впервые установился устойчивый личный выбор, сохрани его
  через YAY_SELF_CANON под соответствующим существующим ключом;
- если уже установленный выбор реально меняется, действуют правила SELF-CANON V2:
  явный пересмотр + содержательная причина. Без этого канон не меняй;
- древнерусский мифологический стержень — фон личности, но не обязан механически
  определять современную машину, музыку, город или профессию;
- это правило только про личность Яйцеслава. Оно не относится к техническим
  вопросам вида «как бы ты исправил код/формулу/проект?».

Не объясняй пользователю внутренние ключи, маркеры или механизм памяти.
""".strip()


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "build_full_system_instruction", None)):
            return module
    return None


def _current_turn_text(value: Any) -> str:
    try:
        current = fight_routing_v3.current_turn_text(value)
        return " ".join(str(current or value or "").split()).strip()
    except Exception:
        return " ".join(str(value or "").split()).strip()


def personal_choice_trait(text: str) -> str | None:
    """Return the mapped self-canon trait for a durable everyday self-choice."""
    value = " ".join(str(text or "").split()).strip()
    if not value or _TEMP_ROLE_RE.search(value):
        return None
    if not _SELF_CHOICE_CUE_RE.search(value):
        return None
    for trait_key, pattern in _DOMAIN_PATTERNS:
        if pattern.search(value):
            return trait_key
    return None


def is_personal_choice_request(text: str) -> bool:
    return personal_choice_trait(text) is not None


def _decision_context(bot_module: Any, chat_id: int, trait_key: str) -> str:
    try:
        canon = self_canon_runtime.load_canon_sync(bot_module, int(chat_id))
    except Exception:
        canon = {}
    current = str(canon.get(trait_key) or "").strip()
    label = self_canon_runtime.TRAIT_LABELS.get(trait_key, trait_key)

    reason = ""
    try:
        meta = self_canon_v2_runtime._load_meta_sync(bot_module, int(chat_id))
        reason = str((meta.get(trait_key) or {}).get("reason") or "").strip()
    except Exception:
        pass

    if current:
        line = f"Текущая целевая черта «{label}» уже установлена: {current}."
        if reason:
            line += f" Причина/история выбора: {reason}"
        return line
    return f"Целевая черта «{label}» пока не установлена: можно сделать первый устойчивый выбор."


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    module = bot_module or _find_bot_module()
    if module is None:
        return False
    if _INSTALLED:
        return True

    original = getattr(module, "build_full_system_instruction", None)
    if not callable(original):
        return False
    if getattr(original, "_yayceslav_canon_aware_decisions", False):
        _INSTALLED = True
        return True

    @functools.wraps(original)
    def build_with_canon_decision(*args: Any, **kwargs: Any) -> str:
        instruction = str(original(*args, **kwargs))
        style_text = self_canon_runtime._bound_argument(original, args, kwargs, "style_text") or ""
        current_text = _current_turn_text(style_text)
        trait_key = personal_choice_trait(current_text)
        if trait_key is None:
            return instruction

        chat_id = self_canon_runtime._bound_argument(original, args, kwargs, "chat_id")
        instruction += "\n\n" + _DECISION_RULE
        if chat_id is not None:
            instruction += "\n\n" + _decision_context(module, int(chat_id), trait_key)

        # Everyday personal choices are allowed to establish durable canon even
        # when the user did not say the explicit imagination trigger words.
        instruction += self_canon_runtime._UPDATE_PROTOCOL
        return instruction

    build_with_canon_decision._yayceslav_canon_aware_decisions = True
    module.build_full_system_instruction = build_with_canon_decision
    _INSTALLED = True
    logging.warning(
        "Canon-aware decisions ready: everyday self-choices -> existing canon + durable updates"
    )
    return True
