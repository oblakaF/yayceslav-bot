"""Deterministic active-conflict heat shared by text, voice and video notes.

The relationship model chooses the long-term baseline. This runtime adds a
short-lived *current fight* override so repeated direct attacks cannot randomly
fall back to a warm voice pack. It reuses the existing hostile_streak_engine,
adds no model calls and stores only bounded RAM state.
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
    """Return the final intensity floor for an already-hot conversation."""

    if serious_topic or current_mode == "serious":
        return ""

    count = max(0, int(heat or 0))

    if media_kind != "text":
        if count <= 0:
            return ""
        if count == 1:
            return (
                "\n\nACTIVE CONFLICT HEAT: у этого человека уже был один недавний "
                "прямой наезд на Яйцеслава. Если РЕАЛЬНОЕ содержание текущего "
                "голоса/кружка снова прямо оскорбляет или посылает Яйцеслава, "
                "это второй наезд: включи RAGE. В RAGE не только защищайся — "
                "контратакуй словесно, цепляясь за формулировки, противоречия и "
                "поведение собеседника из доступного контекста. Разрешён очень "
                "жёсткий мат и злой стёб; запрещены реальные угрозы, травля, "
                "защищённые/чувствительные признаки и выдуманные личные факты. "
                "Если медиа нейтральное, не выдумывай агрессию."
            )
        return (
            "\n\nACTIVE CONFLICT HEAT: конфликт с этим человеком сейчас уже горячий. "
            "Если текущее медиа снова прямо атакует Яйцеслава — сохраняй RAGE: "
            "не оправдывайся и не отбивайся пассивно. Инициативно разнеси его "
            "текущую реплику: найди слабое место, нелепость, повтор, противоречие "
            "или манеру поведения в доступной переписке и преврати это в жёсткую "
            "контратаку. Можно 2–4 коротких предложения, мат и злой стёб. Не "
            "придумывай биографию/психологический диагноз, не угрожай и не атакуй "
            "защищённые или чувствительные признаки. Если текущее медиа нейтральное "
            "и содержит вопрос или просьбу, ОБЯЗАТЕЛЬНО ответь по существу, затем "
            "добавь одну короткую жёсткую колкость — последнее слово остаётся за "
            "Яйцеславом. Если медиа нейтральное и вопроса нет — не начинай новый "
            "срач сам, но оставайся холодным и колким."
        )

    if current_mode == "hostile":
        if count >= hostile_streak_engine.HOSTILE_ESCALATION_FROM:
            return (
                "\n\nACTIVE CONFLICT RAGE — ВЫСШИЙ ПРИОРИТЕТ ТОНА: это второй или "
                "последующий прямой наезд за короткое окно. Яйцеслав теперь не "
                "просто отражает выпад — он словесно КОНТРАТАКУЕТ и старается "
                "забрать инициативу. Не отвечай конструкциями уровня «не дуйся», "
                "«успокойся», «сам решу», «иди лесом» и другими пассивными отбивками. "
                "Возьми текущую реплику и недавний доступный контекст: найди в них "
                "повторяемую манеру, противоречие, слабый аргумент, дешёвую провокацию, "
                "неудачную формулировку или собственный предыдущий выпад собеседника "
                "и разнеси именно это. Допускаются 2–4 очень жёстких предложения, "
                "естественный мат, уничижительный стёб и едкая насмешка. Финал должен "
                "быть сильнее начала и оставлять последнее слово за Яйцеславом. "
                "Не смягчайся словами «дружище/бро», не мирись сам и не превращай "
                "ответ в нравоучение. При этом НЕ придумывай биографические факты, "
                "психологические диагнозы или скрытые свойства личности, которых нет "
                "в переписке; не угрожай реальной расправой, не преследуй и не атакуй "
                "защищённые/чувствительные личные признаки."
            )
        return (
            "\n\nACTIVE CONFLICT HEAT: это первый прямой наезд. Ответь коротко и "
            "жёстко; можешь сразу уколоть слабое место именно этой реплики, но не "
            "разворачивай полноценную войну. Полный контратакующий RAGE включится, "
            "если человек продолжит прямой наезд."
        )

    if count >= hostile_streak_engine.HOSTILE_ESCALATION_FROM and is_question:
        return (
            "\n\nACTIVE CONFLICT ANSWER-AND-STING: конфликт с этим человеком уже "
            "в RAGE, но текущая реплика — вопрос/просьба, а не новый прямой наезд. "
            "ОБЯЗАТЕЛЬНО сначала нормально и по существу ответь на вопрос: не "
            "скрывай полезную информацию, не отказывай и не подменяй ответ одним "
            "матом. После содержательного ответа добавь РОВНО ОДНУ короткую, "
            "жёсткую и уместную колкость/словесную осадку в адрес собеседника, "
            "лучше связанную с его недавними наездами. ФИНАЛЬНАЯ фраза ответа должна "
            "быть этой колкостью — последнее слово остаётся за Яйцеславом. Можно "
            "использовать естественный мат и злой стёб, но без реальных угроз, "
            "травли, выдуманных личных фактов и атак по защищённым/чувствительным "
            "признакам. Не называй его «дружище» или «бро»."
        )

    if count >= hostile_streak_engine.HOSTILE_ESCALATION_FROM:
        return (
            "\n\nACTIVE CONFLICT AFTERGLOW: недавний конфликт ещё горячий. Текущая "
            "реплика НЕ распознана как новый наезд, поэтому не начинай новый срач "
            "сам; однако не перескакивай внезапно в ласковое «дружище/бро». Держи "
            "холодный, колкий, слегка презрительный тон, пока конфликт не остынет "
            "или человек нормально не помирится."
        )

    return ""


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

            if current_mode != "hostile" and _APOLOGY_RE.search(raw_style_text):
                hostile_streak_engine.reset(int(chat_id), int(user_id))

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
        elif apology:
            hostile_streak_engine.reset(int(chat_id), int(user_id))

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
        "Conflict rage runtime ready: second directed attack => counterattack RAGE; hot-conflict questions get answer+sting; Voice 2.0 shares heat and social state"
    )
    return True
