"""Ground proof screenshots and terse proof challenges with bounded web search.

Only explicit evidence disputes are intercepted. Ordinary photos still use the
existing handler. The flow is: screenshot -> compact claim/search-query extract
with the existing Gemini vision path -> existing bounded Search 2.0 -> grounded
answer. Conflict tone remains owned by conflict_fsm_runtime.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from google.genai import types
from telegram.constants import ChatAction, ChatType
from telegram.ext import Application, ApplicationHandlerStop, MessageHandler, filters

import conflict_fsm_runtime


_PREPARED_APPLICATION_IDS: set[int] = set()

_EVIDENCE_CAPTION_RE = re.compile(
    r"(?:"
    r"\b(?:пруф\w*|доказательств\w*|официальн\w*\s+(?:сайт|страниц|источник)|источник\w*|ссылк\w*)\b|"
    r"\b(?:посмотри|проверь|глянь|чекни)\b.{0,32}\b(?:скрин\w*|сайт\w*|пруф\w*|источник\w*|официальн\w*)\b|"
    r"\b(?:вот|держи)\b.{0,24}\b(?:скрин\w*|пруф\w*|доказательств\w*)\b|"
    r"\bты\s+(?:ошибся|пиздишь|вр[её]шь|неправ)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_EXTRA_PROOF_TEXT_RE = re.compile(
    r"(?:"
    r"\bпруф\w*\b|\bдокажи\b|\bпроверь\s+(?:сначала|ещ[её]\s+раз)?\b|"
    r"\bофициальн\w*\s+(?:сайт|источник|страниц)\b|"
    r"\bссылк\w*\s+(?:дай|покажи|где)\b|\b(?:дай|покажи|где)\s+ссылк\w*\b"
    r")",
    re.IGNORECASE,
)


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "ask_gemini", None)):
            return module
    return None


def is_evidence_caption(text: str) -> bool:
    return bool(_EVIDENCE_CAPTION_RE.search(str(text or "")))


def is_proof_text(text: str) -> bool:
    return bool(_EXTRA_PROOF_TEXT_RE.search(str(text or "")))


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else None
    except Exception:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            return None
        try:
            payload = json.loads(match.group(0))
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None


def _fallback_query(caption: str) -> str:
    clean = " ".join(str(caption or "").split()).strip()
    clean = re.sub(
        r"\b(?:пруф\w*|проверь|посмотри|глянь|официальн\w*\s+сайт|ты\s+(?:ошибся|пиздишь|вр[её]шь))\b",
        " ",
        clean,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", clean).strip(" ,.!?:;—-")[:280]


async def _vision_claim_query(bot_module: Any, image_bytes: bytes, caption: str) -> tuple[str, list[str]]:
    prompt = (
        "Это screenshot/evidence dispute. Не отвечай пользователю. Извлеки только "
        "проверяемый внешний факт и поисковый запрос. Верни СТРОГО JSON: "
        '{"search_query":"...","visible_claims":["..."],"needs_web":true}. '
        "search_query должен содержать сущность, событие и при наличии дату/длительность; "
        "не включай оскорбления пользователя. Если на скриншоте виден домен или "
        "официальный источник, включи его название в visible_claims. Не решай сам, "
        "правда это или нет.\n\n"
        f"Подпись пользователя: {caption[:500]}"
    )
    raw = await bot_module.ask_gemini(
        contents=[types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"), prompt],
        max_output_tokens=220,
        thinking_level="low",
    )
    payload = _extract_json(raw) or {}
    query = " ".join(str(payload.get("search_query") or "").split()).strip()[:320]
    claims_raw = payload.get("visible_claims") or []
    claims = [" ".join(str(item).split()).strip()[:300] for item in claims_raw if str(item).strip()]
    return query, claims[:6]


def _grounding_prompt(caption: str, claims: list[str], search_context: str) -> str:
    claims_text = "\n".join(f"- {item}" for item in claims) or "- проверяемый claim со скриншота"
    return (
        "Пользователь предъявил screenshot/пруф и оспаривает недавний фактический ответ.\n\n"
        f"Реплика пользователя:\n{caption[:700]}\n\n"
        f"Что видно/заявлено на screenshot:\n{claims_text}\n\n"
        f"Результаты поиска:\n{search_context}\n\n"
        "ПРАВИЛО ИСТИНЫ: результаты текущего поиска и официальный первичный источник "
        "важнее предыдущих ответов бота. Ответь только по этим данным. Если предыдущий "
        "ответ Яйцеслава оказался неверным, прямо исправь факт без оправданий. Если "
        "источники не подтверждают claim — скажи это. Не называй screenshot фейком без "
        "основания в текущих результатах. Тон определяет active conflict FSM."
    )


async def _evidence_photo_handler(update, context) -> None:
    message = getattr(update, "effective_message", None)
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    if message is None or chat is None or user is None or not getattr(message, "photo", None):
        return

    raw_caption = str(getattr(message, "caption", "") or "").strip()
    if not is_evidence_caption(raw_caption):
        return

    bot_module = _find_bot_module()
    if bot_module is None:
        return

    prepared = await bot_module.prepare_request_text(
        update=update,
        context=context,
        original_text=raw_caption,
        default_text="",
    )
    if prepared is None:
        return
    caption = prepared or raw_caption

    if not await bot_module.enforce_rate_limit(update, "media"):
        raise ApplicationHandlerStop

    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        conflict_fsm_runtime.observe_external_text(bot_module, int(chat.id), int(user.id), caption)

    await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
    file_path = Path(bot_module.TEMP_DIR) / f"evidence_{chat.id}_{message.message_id}_{uuid.uuid4().hex}.jpg"

    try:
        photo = message.photo[-1]
        telegram_file = await photo.get_file()
        await telegram_file.download_to_drive(custom_path=str(file_path))
        query, claims = await _vision_claim_query(bot_module, file_path.read_bytes(), caption)
        query = query or _fallback_query(caption)
        if not query:
            await message.reply_text("На скрине вижу спор, но не вытащил конкретный проверяемый факт. Скажи одной фразой, что проверить.")
            raise ApplicationHandlerStop

        results = await bot_module.search_web(query=query, max_results=5)
        if not results:
            await message.reply_text("Проверил, но выдача пустая. Не буду выдумывать, кто тут прав.")
            raise ApplicationHandlerStop

        search_context = bot_module.format_search_results(results)
        prompt = _grounding_prompt(caption, claims, search_context)
        user_settings = await bot_module.get_user_settings(user.id)
        answer = await bot_module.ask_gemini(
            contents=prompt,
            max_output_tokens=420,
            user_settings=user_settings,
            chat_id=int(chat.id),
            chat_type=str(chat.type),
            user_name=(user.full_name or user.username or ""),
            user_id=int(user.id),
            thinking_level="medium",
        )

        urls: list[str] = []
        for item in results:
            url = str(item.get("url") or "").strip()
            if url and url not in urls:
                urls.append(url)
            if len(urls) >= 3:
                break
        if urls and not any(url in answer for url in urls):
            answer = answer.rstrip() + "\n\nИсточники:\n" + "\n".join(f"- {url}" for url in urls)

        await bot_module.send_answer(update, context, answer, source_user_text=caption)
        await bot_module.increment_stat("total_requests")
        await bot_module.increment_stat("photo_requests")
        await bot_module.increment_stat("search_requests")
        await bot_module.increment_stat("bot_answers")
        raise ApplicationHandlerStop
    finally:
        file_path.unlink(missing_ok=True)


def _install_extra_proof_text_routing(bot_module: Any) -> None:
    original = getattr(bot_module, "extract_search_query", None)
    if not callable(original) or getattr(original, "_yayceslav_evidence_grounding", False):
        return

    def extract_with_proof(text: str):
        existing = original(text)
        if existing is not None:
            return existing
        if is_proof_text(text):
            return ""
        return None

    extract_with_proof._yayceslav_evidence_grounding = True
    bot_module.extract_search_query = extract_with_proof


def prepare_application_runtime(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return

    bot_module = _find_bot_module()
    if bot_module is None:
        logging.warning("Evidence grounding: bot module not ready")
        return

    _install_extra_proof_text_routing(bot_module)
    application.add_handler(MessageHandler(filters.PHOTO, _evidence_photo_handler), group=-6)
    _PREPARED_APPLICATION_IDS.add(app_id)
    logging.warning("Evidence grounding ready: proof screenshots => vision claim extraction + bounded web verification")
