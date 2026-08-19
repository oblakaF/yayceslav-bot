from __future__ import annotations

import logging
import re
import sys
import time
from collections import Counter, defaultdict, deque
from difflib import SequenceMatcher
from typing import Any

from telegram.constants import ChatType

import primitive_compact_guard

# A normal fast group quarrel should not hit the old 5/minute wall.
# Private/expensive media/search limits remain untouched.
GROUP_GENERAL_LIMIT = 12
GROUP_GENERAL_PERIOD_SECONDS = 60.0

_RECENT: dict[tuple[int, int], deque[str]] = defaultdict(lambda: deque(maxlen=8))

_WORD_RE = re.compile(r"[a-zа-яё]{4,}", re.IGNORECASE)
_STOPWORDS = {
    "котор", "этого", "тебя", "тебе", "себя", "свою", "свои", "свой",
    "просто", "вообще", "только", "потом", "сейчас", "здесь", "тут",
    "чтобы", "потому", "когда", "если", "было", "будет", "тоже", "уже",
    "очень", "какой", "какая", "какие", "чего", "меня",
    "нахуй", "отъебись", "блядь", "сука",
}

_FALLBACKS = (
    "Заело тебя. Следующую мысль рожай.",
    "Этот панч уже был. Обнови прошивку.",
    "Повтор засчитан. Что-нибудь свежее будет?",
    "Пластинка по кругу пошла. Давай новый материал.",
    "Ты это уже сказал. Второй дубль смешнее не стал.",
)


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "ask_gemini", None)):
            return module
    return None


def _normalize(text: str) -> str:
    text = (text or "").lower().replace("ё", "е")
    text = re.sub(r"\s+", " ", re.sub(r"[^a-zа-я0-9 ]+", " ", text))
    return text.strip()


def _content_words(text: str) -> set[str]:
    words = set()
    for word in _WORD_RE.findall((text or "").lower().replace("ё", "е")):
        if word in _STOPWORDS:
            continue
        # Crude prefix reduction is enough to catch repeated
        # «интеллект / интеллектуальных» without a heavyweight stemmer.
        key = word[:8] if len(word) >= 8 else word
        words.add(key)
    return words


def _too_similar(candidate: str, recent: deque[str]) -> bool:
    normalized = _normalize(candidate)
    if not normalized:
        return False

    candidate_words = _content_words(candidate)
    recent_word_counts: Counter[str] = Counter()

    for old in recent:
        old_norm = _normalize(old)
        if not old_norm:
            continue
        if normalized == old_norm:
            return True
        if SequenceMatcher(None, normalized, old_norm).ratio() >= 0.80:
            return True

        old_words = _content_words(old)
        if candidate_words and old_words:
            union = candidate_words | old_words
            if union and len(candidate_words & old_words) / len(union) >= 0.58:
                return True
        recent_word_counts.update(old_words)

    # Catch semantic tics like five different jokes built around «интеллект».
    recurring = {word for word, count in recent_word_counts.items() if count >= 2}
    if recurring and candidate_words & recurring:
        return True

    return False


def _recent_instruction(recent: deque[str]) -> str:
    if not recent:
        return ""
    samples = "\n".join(
        f"- {item[:180]!r}"
        for item in list(recent)[-5:]
        if item
    )
    if not samples:
        return ""
    return (
        "\n\nАНТИПОВТОР ДЛЯ ТЕКУЩЕЙ ПЕРЕПАЛКИ:\n"
        "Ниже недавние ответы Яйцеслава этому же человеку. "
        "Не повторяй ни формулировку, ни центральную шутку, ни один и тот же "
        "образ/мишень вроде «интеллект» несколько раз подряд. "
        "Если пользователь повторяет «нет ты», не зеркаль один и тот же "
        "«сам иди нахуй» снова: меняй стратегию — сухой абсурд, буквальное "
        "прочтение, короткий verdict, самоирония, техническая аналогия или "
        "вообще один лаконичный отбой. Недавние ответы:\n"
        + samples
    )


def _latest_user_text(contents: Any) -> str:
    if isinstance(contents, str):
        try:
            return primitive_compact_guard.latest_user_text(contents)
        except Exception:
            return contents
    return ""


def _mode(bot_module, contents: Any) -> str:
    text = _latest_user_text(contents)
    try:
        return str(bot_module.detect_conversation_mode(text))
    except Exception:
        return ""


def _patch_build_instruction(bot_module) -> None:
    if getattr(bot_module, "_yayceslav_anti_repeat_instruction_patch", False):
        return

    original = bot_module.build_full_system_instruction

    def wrapped(*args, **kwargs):
        instruction = original(*args, **kwargs)
        chat_id = kwargs.get("chat_id")
        user_id = kwargs.get("user_id")
        if chat_id is None or user_id is None:
            return instruction

        style_text = args[0] if args else kwargs.get("style_text", "")
        try:
            mode = str(bot_module.detect_conversation_mode(str(style_text or "")))
        except Exception:
            mode = ""
        if mode not in {"hostile", "challenge"}:
            return instruction

        recent = _RECENT.get((int(chat_id), int(user_id)))
        if recent:
            instruction += _recent_instruction(recent)
        return instruction

    bot_module.build_full_system_instruction = wrapped
    bot_module._yayceslav_anti_repeat_instruction_patch = True


def _patch_ask_gemini(bot_module) -> None:
    if getattr(bot_module, "_yayceslav_anti_repeat_gemini_patch", False):
        return

    original = bot_module.ask_gemini

    async def wrapped(*args, **kwargs):
        contents = kwargs.get("contents", args[0] if args else "")
        chat_id = kwargs.get("chat_id")
        user_id = kwargs.get("user_id")
        chat_type = str(kwargs.get("chat_type", ""))

        result = await original(*args, **kwargs)

        if (
            chat_id is None
            or user_id is None
            or chat_type not in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup")
        ):
            return result

        key = (int(chat_id), int(user_id))
        recent = _RECENT[key]
        mode = _mode(bot_module, contents)

        # Keep normal/serious factual answers out of the hostile history.
        if mode not in {"hostile", "challenge"}:
            return result

        if not _too_similar(str(result or ""), recent):
            recent.append(str(result or ""))
            return result

        first = str(result or "")
        recent.append(first)
        logging.info(
            "Hostile anti-repeat retry chat=%s user=%s first=%r",
            chat_id,
            user_id,
            first[:140],
        )

        # One retry only. build_full_system_instruction now sees the rejected
        # answer in RECENT and explicitly bans its wording/theme.
        try:
            retry = await original(*args, **kwargs)
        except Exception:
            retry = ""

        if retry and not _too_similar(str(retry), recent):
            recent.append(str(retry))
            return retry

        # Rotating fallback, never the same one twice.
        index = (len(recent) + int(user_id)) % len(_FALLBACKS)
        fallback = _FALLBACKS[index]
        if recent and _normalize(fallback) == _normalize(recent[-1]):
            fallback = _FALLBACKS[(index + 1) % len(_FALLBACKS)]
        recent.append(fallback)
        return fallback

    bot_module.ask_gemini = wrapped
    bot_module._yayceslav_anti_repeat_gemini_patch = True


def _patch_group_rate_limit(bot_module) -> None:
    if getattr(bot_module, "_yayceslav_group_rate_limit_patch", False):
        return

    original = bot_module.enforce_rate_limit

    async def wrapped(update, bucket: str):
        chat = getattr(update, "effective_chat", None)
        user = getattr(update, "effective_user", None)
        if (
            bucket == "general"
            and chat is not None
            and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
            and user is not None
        ):
            key = (int(user.id), bucket)
            now = time.monotonic()
            queue = bot_module.REQUEST_TIMES[key]
            while queue and now - queue[0] >= GROUP_GENERAL_PERIOD_SECONDS:
                queue.popleft()
            if len(queue) >= GROUP_GENERAL_LIMIT:
                # A canned «пулемётчик» line in the middle of banter looks
                # like a random personality switch. Excess is silently dropped.
                return False
            queue.append(now)
            return True
        return await original(update, bucket)

    bot_module.enforce_rate_limit = wrapped
    bot_module._yayceslav_group_rate_limit_patch = True


def _prepare() -> None:
    bot_module = _find_bot_module()
    if bot_module is None:
        logging.warning("Dialogue guard runtime: bot module not ready")
        return
    _patch_build_instruction(bot_module)
    _patch_ask_gemini(bot_module)
    _patch_group_rate_limit(bot_module)
    logging.warning(
        "Dialogue guard ready: hostile anti-repeat + group general limit 12/min"
    )
