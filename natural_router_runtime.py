"""Deterministic natural-language routing for existing Yayceslav actions.

The router intentionally handles only high-confidence phrases. Anything
ambiguous falls through to the ordinary Gemini text handler, so this layer
adds convenience without turning every chat message into a command.
"""

from __future__ import annotations

import logging
import re
import sys

from telegram.constants import ChatType
from telegram.ext import Application, ApplicationHandlerStop, MessageHandler, filters


_PREPARED_APPLICATION_IDS: set[int] = set()


def _norm(text: str) -> str:
    return re.sub(r"[^\wёЁ]+", " ", (text or "").lower(), flags=re.UNICODE).strip()


_ROUTE_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        "recap",
        (
            re.compile(r"\bчто\s+(?:я\s+)?пропустил\b", re.I),
            re.compile(r"\bчто\s+(?:тут|здесь|в\s+чате)\s+(?:было|происходило)\b", re.I),
            re.compile(r"\bперескажи\s+(?:чат|переписку)\b", re.I),
        ),
    ),
    (
        "leaderboard",
        (
            re.compile(r"\bкто\s+(?:больше|больше\s+всех)\s+писал\b", re.I),
            re.compile(r"\bкто\s+самый\s+активн\w*\b", re.I),
            re.compile(r"\bтоп\s+(?:писателей|активных|болтунов)\b", re.I),
        ),
    ),
    (
        "judge",
        (
            re.compile(r"\bрассуди\s+(?:нас|спор|это)\b", re.I),
            re.compile(r"\bкто\s+(?:из\s+нас\s+)?прав\b", re.I),
            re.compile(r"\bвынеси\s+вердикт\b", re.I),
            re.compile(r"\bоцени\s+спор\b", re.I),
        ),
    ),
    (
        "fact_or_bayan",
        (
            re.compile(r"\bпроверь\s+(?:это\s+)?(?:правда|факт)\b", re.I),
            re.compile(r"\bэто\s+правда\s+или\s+нет\b", re.I),
            re.compile(r"\bфакт\s+или\s+баян\b", re.I),
            re.compile(r"\bпроверь\s+утверждение\b", re.I),
        ),
    ),
    (
        "roast",
        (
            re.compile(r"\bпрожарь\b", re.I),
            re.compile(r"\bподколи\s+(?:его|её|это|сообщение)\b", re.I),
        ),
    ),
    (
        "debate",
        (
            re.compile(r"\bаргументы\s+за\s+и\s+против\b", re.I),
            re.compile(r"\bразбери\s+(?:это\s+)?с\s+двух\s+сторон\b", re.I),
        ),
    ),
    (
        "argument",
        (
            re.compile(r"\bприведи\s+аргумент\b", re.I),
            re.compile(r"\bвозрази\s+(?:ему|ей|этому)\b", re.I),
        ),
    ),
    (
        "meme",
        (
            re.compile(r"\bсделай\s+(?:из\s+этого\s+)?мем\b", re.I),
            re.compile(r"\bпридумай\s+мемн\w*\s+подпис\w*\b", re.I),
        ),
    ),
    (
        "week",
        (
            re.compile(r"\bдай\s+отч[её]т\s+за\s+неделю\b", re.I),
            re.compile(r"\bчто\s+было\s+за\s+неделю\b", re.I),
        ),
    ),
    (
        "awards",
        (
            re.compile(r"\bнаграды\s+недели\b", re.I),
            re.compile(r"\bкто\s+получил\s+награды\b", re.I),
        ),
    ),
)


def classify_action(text: str) -> str | None:
    normalized = _norm(text)
    if not normalized:
        return None
    for action, patterns in _ROUTE_PATTERNS:
        if any(pattern.search(normalized) for pattern in patterns):
            return action
    return None


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "prepare_request_text", None)):
            return module
    return None


async def _route_message(update, context) -> None:
    bot_module = _find_bot_module()
    if bot_module is None or not update.effective_message or not update.effective_chat:
        return

    original_text = str(getattr(update.effective_message, "text", "") or "")
    if not original_text:
        return

    # Reuse the bot's own group-address rules. In private every text is eligible;
    # in groups only direct mentions/replies/text-addresses are routed.
    prepared = await bot_module.prepare_request_text(
        update=update,
        context=context,
        original_text=original_text,
        default_text="",
    )
    if prepared is None:
        return

    action = classify_action(prepared)
    if action is None:
        return

    handler_name = {
        "recap": "recap_command",
        "leaderboard": "leaderboard_command",
        "judge": "judge_command",
        "fact_or_bayan": "fact_or_bayan_command",
        "roast": "roast_command",
        "debate": "debate_command",
        "argument": "argument_command",
        "meme": "meme_command",
        "week": "week_command",
        "awards": "awards_command",
    }[action]
    handler = getattr(bot_module, handler_name, None)
    if not callable(handler):
        logging.warning("Natural router: handler missing for %s (%s)", action, handler_name)
        return

    # These actions are group-centric; avoid surprising private-chat routing
    # for analytics commands that already make little sense in DMs.
    if action in {"recap", "leaderboard", "week", "awards"} and update.effective_chat.type == ChatType.PRIVATE:
        return

    logging.info("Natural router: %s -> %s", prepared[:120], action)
    await handler(update, context)
    raise ApplicationHandlerStop


def prepare_application_runtime(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _route_message),
        group=-2,
    )
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning("Natural-language action router ready")
