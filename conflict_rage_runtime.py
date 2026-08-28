"""Deterministic active-conflict heat shared by text, voice and video notes.

Relationship/reputation choose the normal baseline. Once a concrete user sends
two directed attacks inside the bounded 10-minute window, this runtime latches a
short-lived RAGE override for that (chat, user). Neutral turns and apologies do
not instantly erase the latch: normal tone returns only after ten minutes with
no new directed attack. No extra model calls or persistent storage are added.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import re
import sys
from typing import Any, Mapping, Sequence

import hostile_streak_engine
from personality import HOSTILE_RE


_INSTALLED = False
_GROUP_CHAT_TYPES = {"group", "supergroup"}
_APOLOGY_RE = re.compile(
    r"(?:^|\b)(?:извини(?:сь|те)?|прости(?:те)?|сорян|сори|виноват|мир)(?:\b|$)",
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(
    r"(?:\?|^\s*(?:что|че|чё|кто|где|когда|почему|зачем|как|сколько|какой|какая|какие|"
    r"можешь|скажи|объясни|проверь|посмотри|глянь|расскажи)\b)",
    re.IGNORECASE,
)
_PROACTIVE_VIDEO_MARKERS = (
    "тебя никто не звал",
    "сам решил вклиниться",
    "видео-кружок",
)
_VOICE_MEDIA_MARKERS = (
    "прослушай сообщение пользователя",
    "полную расшифровку не делай",
)


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "build_full_system_instruction", None)):
            return module
    return None


def _call_argument(
    args: Sequence[Any],
    kwargs: Mapping[str, Any],
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


def _media_kind(style_text: str) -> str:
    lowered = str(style_text or "").lower()
    if all(marker in lowered for marker in _PROACTIVE_VIDEO_MARKERS):
        return "proactive_video"
    if any(marker in lowered for marker in _VOICE_MEDIA_MARKERS):
        return "voice_or_audio"
    return "text"


def _looks_like_question(text: str) -> bool:
    value = " ".join(str(text or "").split()).strip()
    return bool(value and _QUESTION_RE.search(value))


def build_conflict_instruction(
    heat: int,
    *,
    current_mode: str,
    media_kind: str,
    serious_topic: bool,
    is_question: bool = False,
) -> str:
    """Return the final conflict phase contract for one response."""

    if serious_topic or current_mode == "serious":
        return ""

    count = max(0, int(heat or 0))
    escalated = hostile_streak_engine.is_escalated(count)

    if media_kind != "text":
        if count <= 0:
            return ""
        if not escalated:
            return (
                "\n\nACTIVE CONFLICT WARNING: у этого человека уже был один недавний "
                "прямой наезд. Если РЕАЛЬНОЕ содержание текущего голоса/кружка "
                "снова прямо атакует Яйцеслава, это второй наезд и должен включить "
                "RAGE. Если медиа нейтральное, не считай его вторым наездом."
            )
        return (
            "\n\nACTIVE CONFLICT RAGE LATCH: с этим человеком уже был второй прямой "
            "наезд, поэтому RAGE ЗАФИКСИРОВАН для конкретной пары чат+человек. "
            "Он не сбрасывается одной нейтральной репликой, примирительным словом "
            "или сменой темы; нормальный baseline вернётся автоматически только "
            "после 10 минут без нового прямого наезда. Пока latch активен, не "
            "становись дружелюбным и не переходи в пассивную защиту. Если текущее "
            "медиа содержит обычный вопрос/просьбу — выполни её по существу, но "
            "заверши короткой злой осадкой. Если это новый наезд — контратакуй "
            "коротко и жёстко по реальному контексту. Без реальных угроз, доксинга "
            "и атак по защищённым признакам."
        )

    # The first directed hit gets one warning only. If the user calms down here,
    # there is no RAGE latch yet and ordinary relationship tone may resume.
    if not escalated:
        if current_mode == "hostile" and count == 1:
            return (
                "\n\nACTIVE CONFLICT WARNING: это первый прямой наезд. Не устраивай "
                "полноценную войну: одна короткая спокойная осадка уровня «полегче» "
                "или один сухой подкол. Не оправдывайся и не читай мораль. Второй "
                "прямой наезд в течение 10 минут включает RAGE."
            )
        return ""

    # From the second hit onward the phase is latched. A neutral message must no
    # longer downgrade it to an AFTERGLOW/relationship baseline; only the 10 min
    # no-new-hostility TTL in hostile_streak_engine can return this user to normal.
    if current_mode == "hostile":
        return (
            "\n\nACTIVE CONFLICT RAGE — ЖЁСТКО ЗАФИКСИРОВАН: это второй или "
            "последующий прямой наезд. Не защищайся пассивно — контратакуй и "
            "забирай инициативу. Цепляйся за реально видимые повторы, противоречия, "
            "дешёвые провокации, формулировки и устойчивую манеру поведения в "
            "недавней переписке. Ответ короткий, злой и направленный на текущий "
            "срач; финальная фраза сильнее начала. Не объявляй диалог оконченным, "
            "не проси конструктив, не называй человека «дружище/бро» и не мирись "
            "сам. Можно естественный мат и едкий бытовой стёб. Без реальных угроз, "
            "доксинга и атак по защищённым признакам."
        )

    if is_question:
        return (
            "\n\nACTIVE CONFLICT RAGE — ANSWER-AND-STING: RAGE с этим человеком "
            "уже зафиксирован вторым наездом, но текущая реплика содержит вопрос "
            "или просьбу. ОБЯЗАТЕЛЬНО дай полезный ответ по существу, затем закончи "
            "одной короткой жёсткой осадкой по недавнему конфликту. Не становись "
            "дружелюбным, не отказывайся выполнять просьбу и не превращай ответ в "
            "простыню. Latch остаётся активным до 10 минут без нового наезда."
        )

    return (
        "\n\nACTIVE CONFLICT RAGE — LATCH STILL ACTIVE: текущая реплика сама по "
        "себе не распознана как новый наезд, но после второго наезда нормальный "
        "relationship baseline ещё НЕ возвращается. Пока не прошло 10 минут без "
        "новой атаки, оставайся злым, колким и недружелюбным. Отреагируй на "
        "содержание, но не начинай лекцию о границах и не объявляй срач законченным. "
        "Короткая контратака/осадка предпочтительнее пассивного «я не буду спорить»."
    )


async def _mirror_voice_social_state(
    bot_module: Any,
    chat_id: int,
    user_id: int,
    *,
    transcript: str,
    hostile: bool,
    apology: bool,
) -> None:
    """Make addressed media affect the same bounded social state as text."""

    try:
        import relationship_experience_runtime as relationship_runtime

        current_date = bot_module.current_msk_datetime().date().isoformat()
        if hostile:
            await asyncio.to_thread(
                relationship_runtime._record_insult_sync,
                bot_module,
                int(chat_id),
                int(user_id),
                current_date,
            )
        elif apology:
            # Apology may repair the persistent/day-level relationship, but it
            # intentionally does NOT clear the short RAGE latch immediately.
            existing = await asyncio.to_thread(
                relationship_runtime._hostility_today_sync,
                bot_module,
                int(chat_id),
                int(user_id),
                current_date,
            )
            if int(existing.get("active_insults", 0) or 0) > 0:
                if bool(existing.get("penance_pending")) or int(existing.get("forgiveness_count", 0) or 0) > 0:
                    await asyncio.to_thread(
                        relationship_runtime._record_relapse_apology_sync,
                        bot_module,
                        int(chat_id),
                        int(user_id),
                        current_date,
                    )
                else:
                    await asyncio.to_thread(
                        relationship_runtime._record_first_apology_sync,
                        bot_module,
                        int(chat_id),
                        int(user_id),
                        current_date,
                    )
    except Exception as error:
        logging.warning("Conflict rage: media daily hostility mirror failed: %s", error)

    if hostile:
        try:
            import reputation_engine
            import reputation_runtime

            decision = reputation_engine.score_message(
                transcript,
                directed_at_bot=True,
                hostile_mode=True,
            )
            if decision.delta:
                await asyncio.to_thread(
                    reputation_runtime._apply_delta_sync,
                    bot_module,
                    int(chat_id),
                    int(user_id),
                    int(decision.delta),
                    f"media_{decision.reason}",
                )
        except Exception as error:
            logging.warning("Conflict rage: media reputation mirror failed: %s", error)


def _install_instruction_wrapper(bot_module: Any) -> None:
    original = bot_module.build_full_system_instruction
    if getattr(original, "_yayceslav_conflict_rage", False):
        return

    @functools.wraps(original)
    def build_with_conflict_rage(*args: Any, **kwargs: Any) -> str:
        raw_style_text = str(
            _call_argument(args, kwargs, name="style_text", position=0, default="") or ""
        )
        instruction = str(original(*args, **kwargs))

        chat_type = str(
            _call_argument(args, kwargs, name="chat_type", position=4, default="") or ""
        ).lower()
        chat_id = _call_argument(args, kwargs, name="chat_id", position=3, default=None)
        user_id = _call_argument(args, kwargs, name="user_id", position=9, default=None)
        if chat_type not in _GROUP_CHAT_TYPES or chat_id is None or user_id is None:
            return instruction

        media_kind = _media_kind(raw_style_text)
        if media_kind == "proactive_video":
            return instruction

        if media_kind == "text":
            try:
                current_mode = str(bot_module.detect_conversation_mode(raw_style_text))
            except Exception:
                current_mode = "normal"
            try:
                serious_topic = bool(bot_module.is_serious_text(raw_style_text))
            except Exception:
                serious_topic = current_mode == "serious"

            # Do NOT reset heat on "извини/сорян". The apology is still recorded
            # in persistent social history, but this short fight remains latched
            # until its own 10-minute no-new-attack TTL expires.
            heat = hostile_streak_engine.current(int(chat_id), int(user_id))
            question = _looks_like_question(raw_style_text)
        else:
            current_mode = "media_unknown"
            serious_topic = False
            question = False
            heat = hostile_streak_engine.current(int(chat_id), int(user_id))

        return instruction + build_conflict_instruction(
            heat,
            current_mode=current_mode,
            media_kind=media_kind,
            serious_topic=serious_topic,
            is_question=question,
        )

    build_with_conflict_rage._yayceslav_conflict_rage = True
    bot_module.build_full_system_instruction = build_with_conflict_rage


def _install_voice2_post_hook(bot_module: Any) -> None:
    try:
        import voice2_runtime
    except Exception as error:
        logging.warning("Conflict rage: Voice 2.0 import unavailable: %s", error)
        return

    original = voice2_runtime._structured_voice_decision
    if getattr(original, "_yayceslav_conflict_rage", False):
        return

    @functools.wraps(original)
    async def structured_with_conflict_heat(module: Any, contents: Any, kwargs: dict[str, Any]) -> str:
        raw = await original(module, contents, kwargs)

        chat_id = kwargs.get("chat_id")
        user_id = kwargs.get("user_id")
        chat_type = str(kwargs.get("chat_type", "") or "").lower()
        if chat_type not in _GROUP_CHAT_TYPES or chat_id is None or user_id is None:
            return raw

        try:
            payload = json.loads(raw)
        except Exception:
            return raw

        transcript = " ".join(str(payload.get("transcript") or "").split()).strip()
        if not transcript:
            return raw

        hostile = bool(HOSTILE_RE.search(transcript))
        apology = bool(_APOLOGY_RE.search(transcript)) and not hostile

        if hostile:
            hostile_streak_engine.observe(int(chat_id), int(user_id), hostile=True)
        # Apology deliberately does not reset the short RAGE latch. Ten quiet
        # minutes from the last directed attack are required to return to normal.

        if hostile or apology:
            await _mirror_voice_social_state(
                bot_module,
                int(chat_id),
                int(user_id),
                transcript=transcript,
                hostile=hostile,
                apology=apology,
            )

        return raw

    structured_with_conflict_heat._yayceslav_conflict_rage = True
    voice2_runtime._structured_voice_decision = structured_with_conflict_heat


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    module = bot_module or _find_bot_module()
    if module is None:
        return False

    _install_instruction_wrapper(module)
    _install_voice2_post_hook(module)
    _INSTALLED = True
    logging.warning(
        "Conflict rage runtime ready: first hit=warning; second hit=latch; normal tone returns after 10 quiet minutes"
    )
    return True
