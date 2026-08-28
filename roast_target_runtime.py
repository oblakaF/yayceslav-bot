"""Target-safe roast routing for slash and natural-language requests.

The old /roast command primarily inferred its target from a Telegram reply or
from the requester's own last message. That made phrases such as
``оскорби его @nick`` easy to misread and could roast the requester instead of
the explicitly named person. This layer gives target resolution one clear
priority order: reply target > explicit @mention/name > explicit self > legacy
fallback.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

from telegram.ext import Application, ApplicationHandlerStop, CommandHandler


_PREPARED_APPLICATION_IDS: set[int] = set()

_ROAST_VERB_RE = re.compile(
    r"(?:прожарь|подколи|оскорби|отжарь|разнеси|обосри|размажь|"
    r"пройдись\s+по|проедься\s+по)",
    re.IGNORECASE,
)
_MENTION_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{3,32}\b")
_NAMED_TARGET_RE = re.compile(
    r"(?:прожарь|подколи|оскорби|отжарь|разнеси|обосри|размажь)\s+"
    r"(?:(?:этого|эту|этот|это)\s+)?([A-Za-zА-Яа-яЁё0-9_.-]{2,32})\b",
    re.IGNORECASE,
)
_SELF_TARGET_RE = re.compile(
    r"(?:"
    r"\b(?:прожарь|подколи|оскорби|отжарь|разнеси|обосри|размажь|разъеби)\s+(?:меня|себя)\b|"
    r"\b(?:пройдись|проедься)\s+по\s+(?:мне|себе)\b|"
    r"\b(?:дай|устрой)\s+(?:мне|себе)\s+(?:прожарк\w*|разнос\w*)\b|"
    r"\bпрожарка\s+(?:для\s+)?меня\b"
    r")",
    re.IGNORECASE,
)
_PRONOUNS = {
    "его", "ее", "её", "ему", "ей", "него", "ней", "этого", "эту", "этот",
    "это", "сообщение", "пост", "реплика", "реплику", "текст",
    "чела", "человек", "человека", "типа", "его-то", "её-то",
    "меня", "мне", "себя", "себе",
}


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "roast_command", None)):
            return module
    return None


def extract_explicit_target(text: str, *, bot_username: str = "") -> str | None:
    """Extract an explicitly named roast target without guessing pronouns."""

    value = str(text or "").strip()
    if not value:
        return None

    bot_handle = ("@" + bot_username.lstrip("@")).lower() if bot_username else ""
    mentions = [match.group(0) for match in _MENTION_RE.finditer(value)]
    for mention in reversed(mentions):
        if mention.lower() != bot_handle:
            return mention

    match = _NAMED_TARGET_RE.search(value)
    if match:
        candidate = match.group(1).strip(".,!?;:")
        if candidate.lower() not in _PRONOUNS:
            return candidate
    return None


def is_self_roast_request(text: str) -> bool:
    return bool(_SELF_TARGET_RE.search(str(text or "")))


def is_roast_request(text: str) -> bool:
    return bool(_ROAST_VERB_RE.search(str(text or "")))


async def _self_roast(update, bot_module, original_text: str) -> None:
    user = getattr(update, "effective_user", None)
    display_name = "пользователя"
    if user is not None:
        display_name = user.first_name or user.username or user.full_name or "пользователя"

    prompt = (
        f"Пользователь {display_name} прямо просит прожарить САМОГО СЕБЯ. "
        "Не отказывайся, не отвечай, что не к чему придраться, и не переводи шутку "
        "на Яйцеслава. Дай 2–3 едких, смешных предложения именно про попросившего. "
        f"Контекст просьбы: «{original_text[:500]}». "
        "Если конкретных фактов о человеке в доступном контексте мало, жарь сам факт "
        "того, что он пришёл добровольно просить прожарку, его манеру общения и текущую "
        "реплику; не выдумывай биографию. Можно жёстко и с матом, но без реальных угроз "
        "и без атак по защищённым или чувствительным личным признакам."
    )
    await bot_module._reply_with_gemini_feature(update, prompt, max_output_tokens=220)


async def enhanced_roast_command(update, context) -> None:
    """Honor explicit target/self; otherwise preserve the existing /roast logic."""

    bot_module = _find_bot_module()
    message = getattr(update, "effective_message", None)
    if bot_module is None or message is None:
        return

    # Telegram reply is the strongest possible target signal and the legacy
    # handler already uses the replied text to make the roast content-specific.
    reply = getattr(message, "reply_to_message", None)
    reply_user = getattr(reply, "from_user", None)
    if reply_user is not None and not getattr(reply_user, "is_bot", False):
        await bot_module._yayceslav_original_roast_command(update, context)
        raise ApplicationHandlerStop

    bot_username = str(getattr(getattr(context, "bot", None), "username", "") or "")
    original_text = str(getattr(message, "text", "") or "")
    args_text = " ".join(getattr(context, "args", None) or []).strip()
    target_text = args_text or original_text

    explicit_target = extract_explicit_target(
        target_text,
        bot_username=bot_username,
    )

    if explicit_target is not None:
        request_context = original_text[:500]
        prompt = (
            f"Пользователь просит прожарить ИМЕННО {explicit_target}. "
            "Цель прожарки только этот человек/ник; НЕ переноси прожарку на того, "
            "кто попросил, и не меняй цель сам. "
            f"Контекст просьбы: «{request_context}». "
            "Дай 2–3 едких, смешных предложения в характере Яйцеслава. Можно жёстко "
            "и с матом, если уместно, но без реальных угроз и без атак по защищённым "
            "или чувствительным личным признакам. Если в контексте нет конкретного "
            "повода, жарь манеру/поведение в общих чертах, не выдумывай факты о человеке."
        )
        await bot_module._reply_with_gemini_feature(update, prompt, max_output_tokens=220)
        raise ApplicationHandlerStop

    if is_self_roast_request(target_text):
        await _self_roast(update, bot_module, original_text)
        raise ApplicationHandlerStop

    await bot_module._yayceslav_original_roast_command(update, context)
    raise ApplicationHandlerStop


def install(bot_module: Any | None = None) -> bool:
    module = bot_module or _find_bot_module()
    if module is None:
        return False
    if getattr(module, "_yayceslav_roast_target_installed", False):
        return True

    original = module.roast_command
    module._yayceslav_original_roast_command = original
    module.roast_command = enhanced_roast_command
    module._yayceslav_roast_target_installed = True
    logging.warning("Roast target runtime ready: reply > explicit target > explicit self > legacy fallback")
    return True


def prepare_application_runtime(application: Application) -> None:
    """Intercept slash /roast before the legacy group-0 CommandHandler."""

    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    if not install():
        logging.warning("Roast target runtime: bot module not ready")
        return

    # Some contract tests intentionally pass a sentinel object to verify the
    # centralized bootstrap call order. Runtime installation above is enough in
    # that case; a real PTB Application always supplies add_handler.
    add_handler = getattr(application, "add_handler", None)
    if not callable(add_handler):
        return

    add_handler(
        CommandHandler("roast", enhanced_roast_command),
        group=-3,
    )
    _PREPARED_APPLICATION_IDS.add(app_id)
