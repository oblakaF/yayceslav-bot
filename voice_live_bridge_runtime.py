"""Bridge live voice semantics into the text persona/self-canon stack.

Voice 2.0 deliberately keeps raw audio and transcripts out of persistent chat
memory. That is good for privacy, but it also means short spoken follow-ups can
lose their referent and the imagination/self-canon layer cannot see the spoken
text when it builds the system prompt.

This bridge keeps only a tiny semantic transcript window in process RAM, never
SQLite, for a short TTL. It also teaches the structured voice turn to treat the
actual spoken request like ordinary text: profanity alone is not hostility,
follow-ups inherit the recent spoken topic, named-entity corrections win, useful
requests are completed before persona flourishes, and first-person hypothetical
preferences may update the existing chat-local self-canon without an extra model
call.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import json
import logging
import sys
import time
from dataclasses import dataclass
from typing import Any

from pydantic import Field

import self_canon_runtime
import voice2_runtime
import voice_runtime


VOICE_CONTEXT_TTL_SECONDS = 15 * 60
VOICE_CONTEXT_MAX_TURNS = 4
VOICE_CONTEXT_MAX_CHATS = 256
VOICE_TRANSCRIPT_MAX_CHARS = 700
VOICE_ANSWER_CONTEXT_MAX_CHARS = 420
VOICE_STRUCTURED_MIN_REQUEST_TOKENS = 512
VOICE_STRUCTURED_TOKEN_CAP = 1024
VOICE_LIVE_ANSWER_MAX_CHARS = 3600

_INSTALLED = False


class VoiceLiveDecision(voice2_runtime.VoiceDecision):
    """VoiceDecision with enough room for requested lists/explanations."""

    answer: str = Field(default="", max_length=VOICE_LIVE_ANSWER_MAX_CHARS)


@dataclass(frozen=True)
class VoiceContextTurn:
    timestamp: float
    transcript: str
    answer: str
    speaker: str = ""


_VOICE_CONTEXT: dict[int, list[VoiceContextTurn]] = {}
_CURRENT_VOICE_CONTEXT: contextvars.ContextVar[str] = contextvars.ContextVar(
    "yayceslav_voice_live_context",
    default="",
)

_VOICE_SERVICE_MARKERS = (
    "Прослушай сообщение пользователя",
    "[Восстановление ответа на голосовое сообщение]",
    "[Восстановление ответа на Telegram video-note]",
)

_VOICE_LIVE_RULE = """

VOICE LIVE SEMANTICS — ТЕКУЩЕЕ АУДИО = ОБЫЧНАЯ РЕПЛИКА ПОЛЬЗОВАТЕЛЯ:
Смысл, который ты услышал в приложенном голосовом/кружке, обрабатывай так же
внимательно, как если бы пользователь напечатал эти слова текстом.

ПРИОРИТЕТЫ:
- СНАЧАЛА выполни нормальный запрос пользователя, ПОТОМ добавляй характер
  Яйцеслава. Характер украшает полезный ответ, а не заменяет его. Не отказывайся
  фразами «я не справочник», «гугли сам», «мне лень», если запрос можно выполнить;
- мат, междометия и грубая разговорная лексика САМИ ПО СЕБЕ НЕ ЯВЛЯЮТСЯ
  hostility. «Бля, посоветуй концерты в Саратове» — обычный запрос. Включай
  hostile/challenge только если наезд, оскорбление, угроза или вызов действительно
  НАПРАВЛЕНЫ на Яйцеслава/собеседника;
- короткие продолжения «это текстом», «а по фазам?», «все фильмы по каждой»,
  «а эта группа?», «что они поют?», «а дальше?» разрешай через недавний VOICE
  CONTEXT ниже. Не спрашивай заново «фазы чего?», если тема уже однозначна;
- текущая голосовая реплика всегда важнее старого контекста. Если пользователь
  исправляет имя/название («нет, называется Drummatix»), ТОЧНОЕ ИСПРАВЛЕНИЕ
  ПОЛЬЗОВАТЕЛЯ имеет приоритет над прошлой ASR-гипотезой;
- для имён групп, людей, фильмов и других сущностей при сомнительном распознавании
  НЕ утверждай уверенно, что «такого не существует», только потому что аудио могло
  распознаться криво. Если нужна актуальная/проверяемая информация — поставь
  needs_search=true и сформируй search_query с ИСПРАВЛЕННЫМ точным названием.
  Если сущность всё ещё реально неоднозначна — задай один короткий уточняющий
  вопрос вместо фантазии;
- search_query относится к ТЕКУЩЕЙ услышанной просьбе. Не переноси туда старую
  несвязанную группу, фильм, человека или тему из предыдущего поиска;
- если человек просит список, порядок, подборку, объяснение или форматирование,
  дай именно это. Большой список можно сделать компактным, но не саботируй задачу
  ради одной шутки или короткого voice-pack панча.

ЛИЧНОСТЬ / ВКУСЫ ЯЙЦЕСЛАВА В ГОЛОСОВОМ:
- вопросы вроде «что бы ТЫ слушал?», «на какой концерт ТЫ бы пошёл?», «что тебе
  нравится?», «какую машину/еду/стиль ты бы выбрал?» — это нормальное приглашение
  выбрать условный личный вкус. Не отвечай «я ИИ», «что я слушаю — неважно» или
  «у меня нет предпочтений». Дай конкретный выбор и короткую причину;
- существующий CHAT-LOCAL SELF CANON, если он есть выше, — текущая версия того же
  Яйцеслава в этом чате. Не противоречь ему без явного нового выбора;
- если в своём ответе ты действительно устанавливаешь или меняешь устойчивую
  черту собственного образа/вкуса, добавь В КОНЕЦ ПОЛЯ `answer` одну скрытую
  строку вида
  [[YAY_SELF_CANON {"set":{"music":"экспериментальная электроника"},"drop":[]}]]
  Используй только допустимые ключи self-canon. Для случайной шутки, навязанного
  пользователем факта или разовой роли маркер НЕ добавляй. Пользователю маркер не
  объясняй — runtime удалит его до отправки.
""".strip()

_AUDIO_POLICY_ADDENDUM = """

VOICE LIVE OVERRIDE:
Мат и слова-паразиты без направленного наезда не делают реплику hostile.
«Бля, посоветуй концерт» и «ну нахуй, дай список фильмов» остаются обычными
информационными запросами. Сначала ответь по задаче, потом добавляй характер.
Если пользователь просит содержательный список/порядок/объяснение, не обрезай
смысл только ради короткого панча; hostile-компактность применяй к реальному
срачу, а не к полезному запросу с матом.
""".strip()


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if (
            module is not None
            and callable(getattr(module, "build_full_system_instruction", None))
            and callable(getattr(module, "ask_gemini", None))
        ):
            return module
    return None


def _normalize_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _prune_context(now: float) -> None:
    cutoff = now - VOICE_CONTEXT_TTL_SECONDS
    for chat_id in list(_VOICE_CONTEXT):
        kept = [turn for turn in _VOICE_CONTEXT[chat_id] if turn.timestamp >= cutoff]
        if kept:
            _VOICE_CONTEXT[chat_id] = kept[-VOICE_CONTEXT_MAX_TURNS:]
        else:
            _VOICE_CONTEXT.pop(chat_id, None)

    if len(_VOICE_CONTEXT) > VOICE_CONTEXT_MAX_CHATS:
        oldest = sorted(
            _VOICE_CONTEXT,
            key=lambda chat_id: _VOICE_CONTEXT[chat_id][-1].timestamp,
        )
        for chat_id in oldest[: len(_VOICE_CONTEXT) - VOICE_CONTEXT_MAX_CHATS]:
            _VOICE_CONTEXT.pop(chat_id, None)


def _remember_voice_turn(
    chat_id: Any,
    transcript: str,
    answer: str = "",
    *,
    speaker: str = "",
    now: float | None = None,
) -> None:
    if chat_id is None:
        return
    clean_transcript = _normalize_text(transcript, VOICE_TRANSCRIPT_MAX_CHARS)
    if not clean_transcript:
        return

    timestamp = float(time.monotonic() if now is None else now)
    _prune_context(timestamp)
    key = int(chat_id)
    turns = _VOICE_CONTEXT.setdefault(key, [])
    turns.append(
        VoiceContextTurn(
            timestamp=timestamp,
            transcript=clean_transcript,
            answer=_normalize_text(answer, VOICE_ANSWER_CONTEXT_MAX_CHARS),
            speaker=_normalize_text(speaker, 80),
        )
    )
    _VOICE_CONTEXT[key] = turns[-VOICE_CONTEXT_MAX_TURNS:]
    _prune_context(timestamp)


def _recent_voice_context(chat_id: Any, *, now: float | None = None) -> str:
    if chat_id is None:
        return ""
    timestamp = float(time.monotonic() if now is None else now)
    _prune_context(timestamp)
    turns = _VOICE_CONTEXT.get(int(chat_id), ())
    if not turns:
        return ""

    lines = [
        "VOICE CONTEXT — короткая RAM-память последних голосовых реплик этого чата;",
        "используй только для разрешения продолжений и ссылок. Текущее аудио важнее:",
    ]
    for turn in turns:
        who = turn.speaker or "пользователь"
        lines.append(f"- {who}: {turn.transcript}")
        if turn.answer:
            lines.append(f"  Яйцеслав: {turn.answer}")
    return "\n".join(lines)


def _is_voice_service_style(style_text: Any) -> bool:
    value = str(style_text or "")
    return any(marker in value for marker in _VOICE_SERVICE_MARKERS)


def _style_text(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if "style_text" in kwargs:
        return kwargs["style_text"]
    return args[0] if args else ""


def _install_prompt_bridge(bot_module: Any) -> None:
    original = getattr(bot_module, "build_full_system_instruction", None)
    if not callable(original) or getattr(original, "_yayceslav_voice_live_bridge", False):
        return

    @functools.wraps(original)
    def build_with_voice_live(*args: Any, **kwargs: Any) -> str:
        instruction = str(original(*args, **kwargs))
        if not _is_voice_service_style(_style_text(args, kwargs)):
            return instruction

        instruction += "\n\n" + _VOICE_LIVE_RULE
        context = _CURRENT_VOICE_CONTEXT.get().strip()
        if context:
            instruction += "\n\n" + context
        return instruction

    build_with_voice_live._yayceslav_voice_live_bridge = True
    bot_module.build_full_system_instruction = build_with_voice_live


def _install_structured_bridge(bot_module: Any) -> None:
    original = voice2_runtime._structured_voice_decision
    if getattr(original, "_yayceslav_voice_live_bridge", False):
        return

    @functools.wraps(original)
    async def structured_with_live_context(
        runtime_bot_module: Any,
        contents: Any,
        kwargs: dict[str, Any],
    ) -> str:
        call_kwargs = dict(kwargs)
        current_requested = int(call_kwargs.get("max_output_tokens", 0) or 0)
        call_kwargs["max_output_tokens"] = max(
            VOICE_STRUCTURED_MIN_REQUEST_TOKENS,
            current_requested,
        )

        chat_id = call_kwargs.get("chat_id")
        speaker = str(call_kwargs.get("user_name") or "")
        context = _recent_voice_context(chat_id)
        token = _CURRENT_VOICE_CONTEXT.set(context)
        try:
            raw = await original(runtime_bot_module, contents, call_kwargs)
        finally:
            _CURRENT_VOICE_CONTEXT.reset(token)

        try:
            payload = json.loads(str(raw or ""))
        except (TypeError, ValueError, json.JSONDecodeError):
            return raw
        if not isinstance(payload, dict):
            return raw

        transcript = _normalize_text(payload.get("transcript"), VOICE_TRANSCRIPT_MAX_CHARS)
        answer = str(payload.get("answer") or "")
        clean_answer, updates, drops = self_canon_runtime.strip_and_parse_canon_marker(answer)

        if chat_id is not None and (updates or drops):
            try:
                await asyncio.to_thread(
                    self_canon_runtime.apply_canon_changes_sync,
                    runtime_bot_module,
                    int(chat_id),
                    updates,
                    drops,
                    clean_answer,
                )
            except Exception as error:
                logging.warning("Voice self-canon write failed for chat %s: %s", chat_id, error)

        payload["answer"] = clean_answer
        if transcript:
            context_answer = clean_answer
            if bool(payload.get("needs_search")):
                query = _normalize_text(payload.get("search_query"), 220)
                context_answer = f"[поиск: {query}]" if query else "[нужен поиск]"
            _remember_voice_turn(
                chat_id,
                transcript,
                context_answer,
                speaker=speaker,
            )

        return json.dumps(payload, ensure_ascii=False)

    structured_with_live_context._yayceslav_voice_live_bridge = True
    voice2_runtime._structured_voice_decision = structured_with_live_context


def _install_recovery_context_bridge() -> None:
    original = voice2_runtime._plain_voice_recovery
    if getattr(original, "_yayceslav_voice_live_bridge", False):
        return

    @functools.wraps(original)
    async def recovery_with_live_context(
        runtime_bot_module: Any,
        contents: Any,
        kwargs: dict[str, Any],
    ) -> str:
        context = _recent_voice_context(kwargs.get("chat_id"))
        token = _CURRENT_VOICE_CONTEXT.set(context)
        try:
            return await original(runtime_bot_module, contents, kwargs)
        finally:
            _CURRENT_VOICE_CONTEXT.reset(token)

    recovery_with_live_context._yayceslav_voice_live_bridge = True
    voice2_runtime._plain_voice_recovery = recovery_with_live_context


def _patch_audio_policy() -> None:
    voice_runtime.AUDIO_REPLY_MAX_OUTPUT_TOKENS = max(
        int(getattr(voice_runtime, "AUDIO_REPLY_MAX_OUTPUT_TOKENS", 0) or 0),
        VOICE_STRUCTURED_TOKEN_CAP,
    )
    current = str(getattr(voice_runtime, "_AUDIO_REPLY_RULE", "") or "")
    if "VOICE LIVE OVERRIDE:" not in current:
        voice_runtime._AUDIO_REPLY_RULE = current.rstrip() + "\n\n" + _AUDIO_POLICY_ADDENDUM


def _patch_voice_decision_schema() -> None:
    # The original structured function resolves VoiceDecision dynamically, so
    # replacing the module global raises only the live voice answer capacity and
    # leaves the rest of its control flow untouched.
    if voice2_runtime.VoiceDecision is not VoiceLiveDecision:
        voice2_runtime.VoiceDecision = VoiceLiveDecision


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    module = bot_module or _find_bot_module()
    if module is None:
        return False
    if _INSTALLED:
        return True

    _patch_voice_decision_schema()
    _patch_audio_policy()
    _install_prompt_bridge(module)
    _install_structured_bridge(module)
    _install_recovery_context_bridge()

    _INSTALLED = True
    logging.warning(
        "Voice live bridge ready: 15m/4-turn RAM context, profanity!=hostility, "
        "task-first voice, entity corrections, persona/self-canon bridge"
    )
    return True
