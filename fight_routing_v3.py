"""Fight / conversation routing v3.

This layer sits on top of the existing conflict FSM instead of replacing it.
It fixes issues observed in live group logs:

* classify tone from the CURRENT user turn, not from the whole remembered chat;
* treat previous sensitive chat claims as claims, not established biography;
* keep ordinary group replies compact and ban the recurring teacher/lecturer tone;
* broaden direct-fight detection for the actual bait wording used in the chat;
* remind the model that it can handle voice/video-note inputs when those inputs
  already reached the multimodal path;
* add one optional post-fight "afterburner": after a real multi-turn RAGE fight,
  Yayceslav may ping the opponent once after a lull using the topic THEY kept
  repeating. It never converts the joke into a personal fact and never chases
  the same person repeatedly.

The afterburner is deliberately RAM-only and costs no extra Gemini call.
"""

from __future__ import annotations

import asyncio
import functools
import html
import logging
import random
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from telegram.constants import ChatType
from telegram.ext import Application, MessageHandler, filters

import conflict_fsm_runtime
import hostile_streak_engine
import primitive_compact_guard


_INSTALLED = False
_PREPARED_APPLICATION_IDS: set[int] = set()

GROUP_COMPACT_MAX_CHARS = 420
GROUP_COMPACT_MAX_SENTENCES = 4
SHORT_BANTER_MAX_CHARS = 320
SHORT_BANTER_MAX_SENTENCES = 3

AFTERBURNER_MIN_HEAT = 3
AFTERBURNER_MIN_DELAY_SECONDS = 4 * 60.0
AFTERBURNER_MAX_DELAY_SECONDS = 8 * 60.0
AFTERBURNER_FIRE_CHANCE = 0.70
AFTERBURNER_SESSION_SECONDS = 10 * 60.0
AFTERBURNER_STICKER_CHANCE = 0.30
AFTERBURNER_SERIOUS_COOLDOWN_SECONDS = 5 * 60.0


_CURRENT_TURN_MARKERS = (
    "Новое обращение к тебе от ",
    "Новое сообщение пользователя:",
)
_SEARCH_RESULTS_MARKER = "Результаты поиска:"

_EXTRA_FIGHT_RE = re.compile(
    r"(?:"
    r"\bты\s+(?:ну\s+и\s+)?(?:залупа|пиздабол|хуесос|у[её]бан|долбо[её]б|мудак|чмо|гумыза)\w*\b|"
    r"\b(?:ху[йя])\s+(?:будешь\s+)?нюхать\b|"
    r"\bнюхал\s+ху[йя]\b|"
    r"\bметнул(?:ся|ась)\s+к\s+ху[йя]\b|"
    r"\b(?:нюхай|нюхать)\s+ху[йя]\b|"
    r"\bты\s+нарываешься\b|"
    r"\bне\s+указывай\s+мне\s+что\s+делать\b.{0,80}\bместо\s+яйцеслава\b|"
    r"\bпапа\s+в\s+прайме\b|"
    r"\bотчество\s+нюх\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_RECONCILE_RE = re.compile(
    r"(?:"
    r"\b(?:сорян|извини|извиняюсь|без\s+обид|проехали|мир|мировая)\b|"
    r"\b(?:перегнул|перегнула|борщанул|борщанула)\b|"
    r"\b(?:обнял|обняла|обнялись)\b|"
    r"\bдавай\s+без\s+срача\b|"
    r"\bвс[её],?\s+норм\b"
    r")",
    re.IGNORECASE,
)

_BAIT_REVEAL_RE = re.compile(
    r"(?:"
    r"\b(?:байт|байтил|байтила|разв[её]л|развела|наебал|наебала|на[её]бка)\b|"
    r"\b(?:шутил|шутила|пошутил|пошутила|прикалывался|прикалывалась)\b|"
    r"\bфотк\w*\s+.{0,24}\b(?:недел|месяц|год)\w*\s+назад\b|"
    r"\bна\s+самом\s+деле\b.{0,50}\b(?:жив|норм|не\s+умер|не\s+было)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_SELF_QUOTE_CHALLENGE_RE = re.compile(
    r"(?:"
    r"\bты\s+(?:мне\s+)?(?:говорил|писал|сказал)\b|"
    r"\bэто\s+не\s+ты\s+(?:мне\s+)?писал\b|"
    r"\bты\s+же\s+(?:говорил|писал)\b|"
    r"\bприписываешь\s+себе\b|"
    r"\bпризнай,?\s+что\s+(?:говорил|писал)\b"
    r")",
    re.IGNORECASE,
)

_EXPLICIT_LONG_RE = re.compile(
    r"(?:"
    r"\b(?:подробно|подробнее|развернуто|разв[её]рнуто|объясни|разъясни|разбери|проанализируй)\b|"
    r"\bрасскажи\s+(?:подробнее|больше|боле|ещ[её])\b|"
    r"\b(?:дай|назови|скинь|перечисли)\s+(?:топ\s*)?\d+\b|"
    r"\bтоп\s*\d+\b|"
    r"\bпо\s+шагам\b|"
    r"\bпошагов\w*\b|"
    r"\bвсе\s+(?:варианты|концерты|причины|способы|пункты)\b"
    r")",
    re.IGNORECASE,
)

_UNKNOWN_WORD_RE = re.compile(
    r"(?:"
    r"\b(?:значение|что\s+значит|что\s+такое|расшифруй)\s+(?:слова\s+)?[«\"']?[\wёЁ-]{3,}[»\"']?\b|"
    r"\bпроверь\s+значение\s+слова\b"
    r")",
    re.IGNORECASE,
)

_SNIFF_THEME_RE = re.compile(
    r"(?:"
    r"\bнюх\w*\b.{0,30}\bху[йя]\w*\b|"
    r"\bху[йя]\w*\b.{0,30}\bнюх\w*\b|"
    r"\bнюх\w*\b.{0,30}\bяйц\w*\b|"
    r"\b(?:сосал|соси)\b|"
    r"\bотчество\s+нюх\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)


_V3_GROUP_RULES = """

V3 ПРАВИЛА ЖИВОГО ГРУППОВОГО ЧАТА:
- Определяй ТОН только по текущей реплике текущего человека. Старая серьёзная,
  медицинская или конфликтная тема другого участника не делает текущий вопрос
  серьёзным или конфликтным.
- История чата — это история того, ЧТО ЛЮДИ СКАЗАЛИ, а не база проверенных
  биографических фактов. Особенно смерть, болезни, травмы, отношения, деньги и
  другие чувствительные заявления. Реагируй на них серьёзно в момент сообщения,
  но не превращай их в установленный факт о человеке без подтверждения.
- Если позже выяснилось, что история была байтом, шуткой, старой фотографией или
  пользователь сам её опроверг, обнови локальный вывод: помни сам эпизод
  («он меня этим байтил»), но НЕ продолжай считать содержание байта правдой.
- Не придумывай характер, привычки, отношения, личные переписки или позицию
  другого участника чата, если этого нет в доступных сообщениях/профиле.
- В несерьёзной болтовне не становись школьным завучем. Не пиши «давай
  конструктивно», «говори по существу», «разговор окончен», «я здесь ради
  адекватного общения», «это не несёт смысловой нагрузки» и похожие лекции,
  если можно просто ответить, подколоть или коротко послать.
- Если тебя ловят на твоей прошлой цитате, сначала проверь доступный контекст.
  Не отрицай уверенно собственные слова, если не уверен. Если поймали честно —
  коротко признай: по смыслу «да, говорил; тут поймал», и двигайся дальше.
- Не выдумывай словарные определения, реальные цитаты, названия песен или
  факты. Для незнакомого сленга скажи, что не уверен; если пользователь просит
  «проверь»/«со ссылками», ищи именно предыдущий предмет разговора.
- Ты умеешь принимать голосовые и Telegram video-note/кружки, когда они уже
  пришли в мультимодальный обработчик. Не заявляй пользователю, что голосовые
  «не к тебе» или что ты работаешь только с текстом.
"""

_SELF_QUOTE_RULE = """

ТЕКУЩИЙ СПОР О СОБСТВЕННЫХ СЛОВАХ:
Пользователь утверждает, что Яйцеслав раньше что-то конкретное говорил/писал.
Считай недавнюю историю диалога и прямую цитату/скрин более надёжными, чем
самоуверенное отрицание. Если фраза действительно видна в контексте — признай
это коротко и без оправданий. Не газлайть собеседника фразой «я такого не говорил».
"""

_UNKNOWN_WORD_RULE = """

ПРОВЕРКА СЛОВА/СЛЕНГА:
Не сочиняй словарную статью. Если значение не знаешь уверенно — скажи это.
Если пользователь просит проверить и дать ссылки, предмет проверки — слово или
выражение из текущей/непосредственно предыдущей реплики, а не случайное служебное
слово вроде «вместе» из формулировки запроса.
"""


@dataclass
class AfterburnerState:
    chat_id: int
    user_id: int
    username: str = ""
    display_name: str = ""
    trigger_message_id: int = 0
    last_rage_answer_at: float = 0.0
    last_user_activity_at: float = 0.0
    target_spoke_after: bool = False
    fired: bool = False
    generation: int = 0
    fight_texts: list[str] = field(default_factory=list)
    task: asyncio.Task[Any] | None = None


_AFTERBURNER_STATES: dict[tuple[int, int], AfterburnerState] = {}
_CHAT_LAST_SERIOUS_AT: dict[int, float] = {}


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "ask_gemini", None)):
            return module
    return None


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


def _replace_argument(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    name: str,
    position: int,
    value: Any,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    new_args = list(args)
    new_kwargs = dict(kwargs)
    if len(new_args) > position:
        new_args[position] = value
    else:
        new_kwargs[name] = value
    return tuple(new_args), new_kwargs


def current_turn_text(value: Any) -> str:
    """Extract only the latest user turn for tone/routing decisions."""

    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""

    if any(marker in text for marker in _CURRENT_TURN_MARKERS):
        try:
            text = primitive_compact_guard.latest_user_text(text).strip()
        except Exception:
            pass

    if f"\n\n{_SEARCH_RESULTS_MARKER}" in text:
        text = text.split(f"\n\n{_SEARCH_RESULTS_MARKER}", 1)[0].strip()
    return text


def is_reconciliation(text: str) -> bool:
    return bool(_RECONCILE_RE.search(str(text or "")))


def is_bait_reveal(text: str) -> bool:
    return bool(_BAIT_REVEAL_RE.search(str(text or "")))


def fight_theme(texts: list[str]) -> str:
    joined = "\n".join(texts[-8:])
    if _SNIFF_THEME_RE.search(joined):
        return "sniff"
    return "generic"


def _patch_conflict_detector() -> None:
    original = conflict_fsm_runtime.is_extra_hostile
    if getattr(original, "_yayceslav_fight_routing_v3", False):
        return

    @functools.wraps(original)
    def extra_hostile_v3(text: str) -> bool:
        value = " ".join(str(text or "").split()).strip()
        return bool(original(value) or (value and _EXTRA_FIGHT_RE.search(value)))

    extra_hostile_v3._yayceslav_fight_routing_v3 = True
    conflict_fsm_runtime.is_extra_hostile = extra_hostile_v3


def _patch_instruction_builder(bot_module: Any) -> None:
    original = bot_module.build_full_system_instruction
    if getattr(original, "_yayceslav_fight_routing_v3", False):
        return

    @functools.wraps(original)
    def build_v3(*args: Any, **kwargs: Any) -> str:
        raw_style = _call_argument(args, kwargs, name="style_text", position=0, default="")
        style_text = current_turn_text(raw_style)
        call_args, call_kwargs = _replace_argument(
            args,
            kwargs,
            name="style_text",
            position=0,
            value=style_text,
        )
        instruction = str(original(*call_args, **call_kwargs))

        chat_type = str(
            _call_argument(call_args, call_kwargs, name="chat_type", position=4, default="")
            or ""
        ).lower()
        if chat_type not in ("group", "supergroup"):
            return instruction

        instruction += _V3_GROUP_RULES
        if _SELF_QUOTE_CHALLENGE_RE.search(style_text):
            instruction += _SELF_QUOTE_RULE
        if _UNKNOWN_WORD_RE.search(style_text):
            instruction += _UNKNOWN_WORD_RULE
        if is_bait_reveal(style_text):
            instruction += (
                "\n\nТЕКУЩАЯ РЕПЛИКА РАСКРЫВАЕТ БАЙТ/ШУТКУ: пересмотри предыдущий "
                "чувствительный вывод. Не храни содержание байта как реальный факт; "
                "можно помнить только сам факт, что человек так подколол/проверил бота."
            )
        return instruction

    build_v3._yayceslav_fight_routing_v3 = True
    bot_module.build_full_system_instruction = build_v3


def _compact_text(text: str, *, max_chars: int, max_sentences: int) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean or len(clean) <= max_chars:
        return clean

    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?…])\s+", clean)
        if part.strip()
    ]
    chosen: list[str] = []
    for sentence in sentences:
        candidate = " ".join(chosen + [sentence]).strip()
        if len(candidate) > max_chars:
            break
        chosen.append(sentence)
        if len(chosen) >= max_sentences:
            break

    if chosen:
        return " ".join(chosen).strip()

    cut = clean[: max_chars - 1].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0].rstrip()
    return cut.rstrip(" ,;:-") + "…"


def _should_keep_long(bot_module: Any, source_text: str, contents: Any, user_settings: Any) -> bool:
    if not source_text:
        return True
    if not isinstance(contents, str):
        # Voice/photo/document control paths have their own schemas/length rules.
        return True
    if _SEARCH_RESULTS_MARKER in contents:
        return True
    if _EXPLICIT_LONG_RE.search(source_text):
        return True
    if isinstance(user_settings, dict) and str(user_settings.get("response_length", "")) == "detailed":
        return True
    try:
        if bot_module.is_serious_text(source_text):
            return True
    except Exception:
        pass
    # Explicit list/count requests need room to actually satisfy the requested N.
    if re.search(r"\b(?:дай|назови|скинь|перечисли|топ)\b.{0,20}\b\d{1,2}\b", source_text, re.IGNORECASE):
        return True
    return False


def _patch_output_compaction(bot_module: Any) -> None:
    original = bot_module.ask_gemini
    if getattr(original, "_yayceslav_fight_routing_v3", False):
        return

    @functools.wraps(original)
    async def ask_v3(contents: Any, *args: Any, **kwargs: Any) -> Any:
        result = await original(contents, *args, **kwargs)
        if not isinstance(result, str):
            return result

        chat_type = str(kwargs.get("chat_type", "") or "").lower()
        if chat_type not in ("group", "supergroup"):
            return result

        source_text = current_turn_text(contents)
        if _should_keep_long(bot_module, source_text, contents, kwargs.get("user_settings")):
            return result

        # conflict_fsm already uses a stricter cap in WARNING/RAGE. Leave it in
        # charge there; this cap is mainly for normal group chatter that used to
        # turn into three-paragraph lectures.
        chat_id = kwargs.get("chat_id")
        user_id = kwargs.get("user_id")
        if chat_id is not None and user_id is not None:
            try:
                if conflict_fsm_runtime.phase(int(chat_id), int(user_id)) is not conflict_fsm_runtime.ConflictPhase.NORMAL:
                    return result
            except Exception:
                pass

        short_banter = len(source_text) <= 180
        return _compact_text(
            result,
            max_chars=SHORT_BANTER_MAX_CHARS if short_banter else GROUP_COMPACT_MAX_CHARS,
            max_sentences=SHORT_BANTER_MAX_SENTENCES if short_banter else GROUP_COMPACT_MAX_SENTENCES,
        )

    ask_v3._yayceslav_fight_routing_v3 = True
    bot_module.ask_gemini = ask_v3


def _mention_html(state: AfterburnerState) -> str:
    if state.username:
        return "@" + state.username.lstrip("@")
    label = state.display_name or f"участник {state.user_id}"
    return f'<a href="tg://user?id={state.user_id}">{html.escape(label)}</a>'


def _pick_afterburner_line(state: AfterburnerState) -> str:
    mention = _mention_html(state)
    theme = fight_theme(state.fight_texts)

    if theme == "sniff" and state.target_spoke_after:
        variants = (
            f"{mention}, с остальными уже разговорчивый? А нюхательную диссертацию мне так и не защитил.",
            f"{mention}, я смотрю, эфир снова поймал. А лекция про нюхать хуй без финала осталась.",
            f"{mention}, на других голос нашёлся? Я уже думал занюх закончился вместе с аргументами.",
        )
    elif theme == "sniff":
        variants = (
            f"{mention}, ну чё, главный специалист по занюху, слился на практической части?",
            f"{mention}, ты куда пропал? Лекция про нюхать хуй закончилась на введении?",
            f"{mention}, ну чё, любитель занюхнуть яйца, батарейка села?",
        )
    elif state.target_spoke_after:
        variants = (
            f"{mention}, с остальными уже разговорчивый? А тут раунд без финального гонга бросил.",
            f"{mention}, вижу, голос вернулся. Мне-то финальный аргумент зажал, чемпион?",
            f"{mention}, эфир ожил, а наш раунд ты так и оставил на паузе. Не вывез концовку?",
        )
    else:
        variants = (
            f"{mention}, ну чё, боец, на третий раунд батарейка села?",
            f"{mention}, так бодро заходил и куда-то испарился. Не вывез концовку?",
            f"{mention}, контрольный вопрос: слился или ещё формулируешь легендарный ответ?",
        )
    return random.choice(variants)


def _cancel_afterburner(key: tuple[int, int], *, drop: bool = False) -> None:
    state = _AFTERBURNER_STATES.get(key)
    if state and state.task and not state.task.done():
        state.task.cancel()
    if drop:
        _AFTERBURNER_STATES.pop(key, None)


def _recent_serious_chat(chat_id: int, now: float) -> bool:
    last = _CHAT_LAST_SERIOUS_AT.get(int(chat_id), 0.0)
    return bool(last and now - last < AFTERBURNER_SERIOUS_COOLDOWN_SECONDS)


async def _maybe_afterburner_sticker(context: Any, state: AfterburnerState) -> None:
    if random.random() >= AFTERBURNER_STICKER_CHANCE:
        return
    try:
        import sticker_runtime

        now = time.monotonic()
        if not sticker_runtime.sticker_slot_allowed(state.chat_id, state.user_id, now):
            return

        theme = fight_theme(state.fight_texts)
        keys = (
            ("ne_vyvez", "obtekay", "slabyy_zahod")
            if theme == "sniff"
            else ("ne_vyvez", "slabyy_zahod", "obtekay")
        )
        mapping = await sticker_runtime.ensure_sticker_ids(context.bot)
        candidates = [mapping.get(key) for key in keys if mapping.get(key)]
        if not candidates:
            return
        await context.bot.send_sticker(chat_id=state.chat_id, sticker=random.choice(candidates))
        sticker_runtime._record_sticker_slot(state.chat_id, state.user_id, now)
    except Exception as error:
        logging.debug("Fight-v3 afterburner sticker skipped: %s", error)


async def _afterburner_wait(
    context: Any,
    key: tuple[int, int],
    generation: int,
    delay: float,
) -> None:
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return

    state = _AFTERBURNER_STATES.get(key)
    if state is None or state.generation != generation or state.fired:
        return

    now = time.monotonic()
    if _recent_serious_chat(state.chat_id, now):
        return
    if now - state.last_rage_answer_at > AFTERBURNER_SESSION_SECONDS:
        return
    if hostile_streak_engine.current(state.chat_id, state.user_id, now=now) < 2:
        return
    if random.random() >= AFTERBURNER_FIRE_CHANCE:
        return

    line = _pick_afterburner_line(state)
    try:
        await context.bot.send_message(
            chat_id=state.chat_id,
            text=line,
            parse_mode="HTML",
        )
        state.fired = True
        await _maybe_afterburner_sticker(context, state)
        logging.info(
            "Fight-v3 afterburner fired chat=%s user=%s theme=%s spoke_after=%s",
            state.chat_id,
            state.user_id,
            fight_theme(state.fight_texts),
            state.target_spoke_after,
        )
    except Exception as error:
        logging.warning(
            "Fight-v3 afterburner send failed chat=%s user=%s: %s",
            state.chat_id,
            state.user_id,
            error,
        )


def _schedule_afterburner(update: Any, context: Any, source_text: str) -> None:
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if (
        chat is None
        or user is None
        or message is None
        or getattr(user, "is_bot", False)
        or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP)
    ):
        return

    key = (int(chat.id), int(user.id))
    if is_reconciliation(source_text):
        _cancel_afterburner(key, drop=True)
        return

    bot_module = _find_bot_module()
    try:
        if bot_module is not None and bot_module.is_serious_text(source_text):
            _CHAT_LAST_SERIOUS_AT[int(chat.id)] = time.monotonic()
            _cancel_afterburner(key, drop=True)
            return
    except Exception:
        pass

    heat = hostile_streak_engine.current(chat.id, user.id)
    try:
        rage = conflict_fsm_runtime.phase(chat.id, user.id) is conflict_fsm_runtime.ConflictPhase.RAGE
    except Exception:
        rage = False
    if not rage or heat < AFTERBURNER_MIN_HEAT:
        return

    now = time.monotonic()
    state = _AFTERBURNER_STATES.get(key)
    if (
        state is None
        or state.fired
        or now - state.last_rage_answer_at > AFTERBURNER_SESSION_SECONDS
    ):
        state = AfterburnerState(
            chat_id=int(chat.id),
            user_id=int(user.id),
        )
        _AFTERBURNER_STATES[key] = state

    if state.fired:
        return

    state.username = str(getattr(user, "username", "") or "")
    state.display_name = str(
        getattr(user, "first_name", "")
        or getattr(user, "full_name", "")
        or state.display_name
        or ""
    )
    state.trigger_message_id = int(getattr(message, "message_id", 0) or 0)
    state.last_rage_answer_at = now
    state.last_user_activity_at = now
    state.target_spoke_after = False
    state.generation += 1

    if source_text:
        state.fight_texts.append(str(source_text)[:300])
        state.fight_texts = state.fight_texts[-8:]

    if state.task and not state.task.done():
        state.task.cancel()

    delay = random.uniform(AFTERBURNER_MIN_DELAY_SECONDS, AFTERBURNER_MAX_DELAY_SECONDS)
    coro = _afterburner_wait(context, key, state.generation, delay)
    create_task = getattr(getattr(context, "application", None), "create_task", None)
    if callable(create_task):
        state.task = create_task(
            coro,
            name=f"fight_afterburner_{chat.id}_{user.id}",
        )
    else:
        state.task = asyncio.create_task(coro)

    logging.info(
        "Fight-v3 afterburner armed chat=%s user=%s heat=%s delay=%.0fs theme=%s",
        chat.id,
        user.id,
        heat,
        delay,
        fight_theme(state.fight_texts),
    )


def _patch_send_answer(bot_module: Any) -> None:
    original = bot_module.send_answer
    if getattr(original, "_yayceslav_fight_routing_v3", False):
        return

    @functools.wraps(original)
    async def send_answer_v3(update: Any, context: Any, text: str, *args: Any, **kwargs: Any):
        result = await original(update, context, text, *args, **kwargs)
        source_user_text = kwargs.get(
            "source_user_text",
            args[2] if len(args) >= 3 else None,
        )
        if source_user_text:
            _schedule_afterburner(update, context, str(source_user_text))
        return result

    send_answer_v3._yayceslav_fight_routing_v3 = True
    bot_module.send_answer = send_answer_v3


async def _observe_group_text(update: Any, context: Any) -> None:
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if (
        chat is None
        or user is None
        or message is None
        or getattr(user, "is_bot", False)
        or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP)
        or not getattr(message, "text", None)
    ):
        return

    text = str(message.text or "")
    now = time.monotonic()
    bot_module = _find_bot_module()
    try:
        if bot_module is not None and bot_module.is_serious_text(text):
            _CHAT_LAST_SERIOUS_AT[int(chat.id)] = now
    except Exception:
        pass

    key = (int(chat.id), int(user.id))
    state = _AFTERBURNER_STATES.get(key)
    if state is None or state.fired:
        return
    if int(getattr(message, "message_id", 0) or 0) == state.trigger_message_id:
        return

    if is_reconciliation(text):
        _cancel_afterburner(key, drop=True)
        return

    state.last_user_activity_at = now
    state.target_spoke_after = True


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    module = bot_module or _find_bot_module()
    if module is None:
        return False
    if _INSTALLED:
        return True

    _patch_conflict_detector()
    _patch_instruction_builder(module)
    _patch_output_compaction(module)
    _patch_send_answer(module)

    _INSTALLED = True
    logging.warning(
        "Fight routing v3 ready: current-turn tone, truth/bait guard, compact group replies, "
        "expanded fight bait, one-shot post-fight afterburner"
    )
    return True


def prepare_application_runtime(application: Application) -> None:
    app_id = id(application)
    if app_id in _PREPARED_APPLICATION_IDS:
        return
    if not install():
        logging.warning("Fight routing v3: bot module not ready")
        return

    add_handler = getattr(application, "add_handler", None)
    if callable(add_handler):
        add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, _observe_group_text),
            group=14,
        )
    _PREPARED_APPLICATION_IDS.add(app_id)
