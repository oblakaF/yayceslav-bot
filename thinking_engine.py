# ============================================================
# YAICESLAV V2 — GEMINI ROUTING, THINKING POLICY AND CHAT GUARDS
# ============================================================

from __future__ import annotations

import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Any


# ============================================================
# THINKING POLICY
# ============================================================

THINKING_MINIMAL = "minimal"
THINKING_LOW = "low"
THINKING_MEDIUM = "medium"

SUPPORTED_LEVELS = {
    THINKING_MINIMAL,
    THINKING_LOW,
    THINKING_MEDIUM,
    "high",
}

_INITIAL_TOKEN_FLOOR = {
    THINKING_MINIMAL: 384,
    THINKING_LOW: 512,
    THINKING_MEDIUM: 768,
    "high": 1024,
}

_COMPLEX_RE = re.compile(
    r"\b(?:"
    r"проанализир\w*|анализ\w*|сравни\w*|сопостав\w*|"
    r"разбери\w*\s+подроб|подробн\w*\s+разбор|"
    r"докажи\w*|обоснуй\w*|аргумент\w*\s+(?:за|против)|"
    r"дебат\w*|пошагов\w*|по\s+шагам|"
    r"плюс\w*\s+и\s+минус\w*|сильн\w*\s+и\s+слаб\w*\s+сторон|"
    r"оцени\w*\s+(?:достоверност|риски|вариант)|"
    r"результат\w*\s+поиск|интернет-проверк\w*|источник\w*"
    r")\b",
    re.IGNORECASE,
)

_EXPLICIT_EXPLAIN_RE = re.compile(
    r"\b(?:объясни\w*|разъясни\w*|растолкуй\w*|разбери\w*)\b",
    re.IGNORECASE,
)

_SUBSTANTIVE_QUESTION_RE = re.compile(
    r"\b(?:почему|каким\s+образом|как\s+работает|что\s+такое|"
    r"что\s+(?:ты\s+)?думаешь|как\s+(?:ты\s+)?считаешь|"
    r"расскажи\w*|зачем|стоит\s+ли)\b",
    re.IGNORECASE,
)

_FAST_STYLE_RE = re.compile(
    r"\b(?:прожарь\w*|мемн\w*\s+подпис|коротк\w*\s+подкол|"
    r"плохой\s+совет|одна[-–— ]две\s+строк)\b",
    re.IGNORECASE,
)

_CASUAL_RE = re.compile(
    r"\b(?:привет|здарова|здорово|ку|лол|кек|ахах\w*|хаха\w*|"
    r"ага|угу|да|нет|ок(?:ей)?|база|кринж|рофл|"
    r"дебил\w*|дурак\w*|нищ\w*|скуф\w*|"
    r"согласен|точно|реально|жиза)\b",
    re.IGNORECASE,
)


def content_to_text(contents: Any) -> str:
    """Extract useful textual content from a Gemini request."""

    if isinstance(contents, str):
        return contents

    if isinstance(contents, (list, tuple)):
        parts: list[str] = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
                continue

            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)

        return "\n".join(parts)

    text = getattr(contents, "text", None)
    return text if isinstance(text, str) else ""


def choose_thinking_level(
    contents: Any,
    *,
    explicit: str | None = None,
) -> str:
    """Choose a latency/quality balance for Gemini."""

    if explicit is not None:
        normalized = explicit.strip().lower()
        if normalized not in SUPPORTED_LEVELS:
            raise ValueError(f"Unsupported thinking level: {explicit}")
        return normalized

    text = content_to_text(contents).strip()
    if not text:
        return THINKING_LOW

    if _COMPLEX_RE.search(text) or _EXPLICIT_EXPLAIN_RE.search(text):
        return THINKING_MEDIUM

    if _FAST_STYLE_RE.search(text):
        return THINKING_MINIMAL

    if _SUBSTANTIVE_QUESTION_RE.search(text):
        return THINKING_MEDIUM if len(text) >= 320 else THINKING_LOW

    words = re.findall(r"[\wёЁ]+", text, flags=re.UNICODE)

    if len(text) <= 120 and len(words) <= 18:
        return THINKING_MINIMAL

    if _CASUAL_RE.search(text) and len(text) <= 220:
        return THINKING_MINIMAL

    return THINKING_LOW


def initial_token_budget(requested: int, thinking_level: str) -> int:
    """Avoid tiny reasoning budgets while preserving visible-length intent."""

    if thinking_level not in SUPPORTED_LEVELS:
        raise ValueError(f"Unsupported thinking level: {thinking_level}")

    requested = max(1, int(requested))
    return max(requested, _INITIAL_TOKEN_FLOOR[thinking_level])


# ============================================================
# GEMINI 3.6 -> 3.1 FALLBACK
# ============================================================

PRIMARY_MODEL = "gemini-3.6-flash"
FALLBACK_MODEL = "gemini-3.1-flash-lite"
PRIMARY_RETRY_SECONDS = 30 * 60

_RAILWAY_DATA_DIR = Path("/app/data")
_STATE_DIR = _RAILWAY_DATA_DIR if _RAILWAY_DATA_DIR.exists() else Path("data")
_STATE_FILE = _STATE_DIR / "gemini_model_router.json"

_primary_blocked_until_epoch = 0.0
_primary_probe_in_progress = False


def _load_router_state() -> None:
    global _primary_blocked_until_epoch

    try:
        payload = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        value = float(payload.get("primary_blocked_until_epoch", 0.0))
        _primary_blocked_until_epoch = max(0.0, value)
    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError, OSError):
        _primary_blocked_until_epoch = 0.0


def _save_router_state() -> None:
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps(
                {"primary_blocked_until_epoch": _primary_blocked_until_epoch},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError as error:
        logging.warning("Gemini router: could not persist cooldown: %s", error)


def _start_primary_cooldown() -> None:
    global _primary_blocked_until_epoch
    _primary_blocked_until_epoch = time.time() + PRIMARY_RETRY_SECONDS
    _save_router_state()


def _clear_primary_cooldown() -> None:
    global _primary_blocked_until_epoch
    _primary_blocked_until_epoch = 0.0
    _save_router_state()


def _is_quota_429(error: BaseException) -> bool:
    for attribute in ("code", "status_code"):
        try:
            if int(getattr(error, attribute, 0) or 0) == 429:
                return True
        except (TypeError, ValueError):
            pass

    text = str(error).upper()
    return "429" in text and (
        "RESOURCE_EXHAUSTED" in text
        or "QUOTA" in text
        or "RATE" in text
    )


def _requested_model(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    if "model" in kwargs:
        value = kwargs.get("model")
        return str(value) if value is not None else None
    if args:
        return str(args[0])
    return None


def _with_model(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    model: str,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    new_kwargs = dict(kwargs)

    if "model" in new_kwargs:
        new_kwargs["model"] = model
        return args, new_kwargs

    if args:
        new_args = list(args)
        new_args[0] = model
        return tuple(new_args), new_kwargs

    new_kwargs["model"] = model
    return args, new_kwargs


def _request_contents(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if "contents" in kwargs:
        return kwargs.get("contents")
    if len(args) >= 2:
        return args[1]
    return None


# ============================================================
# HARD COMPACT REPLY GUARD
# ============================================================

COMPACT_MAX_CHARS = 180
COMPACT_MAX_OUTPUT_TOKENS = 192

_COMPACT_HOSTILE_RE = re.compile(
    r"(?:"
    r"\b(?:нахуй|на\s+хуй|пош[её]л\s+нах|иди\s+нах|соси|заткнись)\b|"
    r"\b(?:хуй|ху[её]в\w*|еблан\w*|долбо[её]б\w*|дебил\w*|"
    r"мудак\w*|чмо|пиздабол\w*|заебал\w*|туп\w*|ишак\w*|"
    r"клоун\w*|убог\w*|сука|сучк\w*)\b|"
    r"\b(?:душн\w*|простын\w*|тавтолог\w*|насрал\w*\s+текст\w*|"
    r"много\s+пиш\w*|много\s+текст\w*|короче\s+отвечай)\b"
    r")",
    re.IGNORECASE,
)

_EXPLICIT_LONG_REQUEST_RE = re.compile(
    r"\b(?:"
    r"объясни\w*|разъясни\w*|расскажи\w*|разбери\w*|подробн\w*|"
    r"проанализир\w*|анализ\w*|сравни\w*|докажи\w*|обоснуй\w*|"
    r"по\s+шагам|пошагов\w*"
    r")\b",
    re.IGNORECASE,
)

_SERIOUS_GUARD_RE = re.compile(
    r"\b(?:"
    r"врач\w*|лекарств\w*|болит|болят|боль|симптом\w*|болезн\w*|"
    r"суицид\w*|умер\w*|смерт\w*|травм\w*|кровотеч\w*|насили\w*|"
    r"кредит\w*|долг\w*|пожар\w*"
    r")\b",
    re.IGNORECASE,
)

# Phrases that reveal the unwanted lecturer / debate-club voice.
_LECTURE_STYLE_RE = re.compile(
    r"\b(?:"
    r"суть\s+претензи\w*|претензи\w*|конструктив\w*|"
    r"содержательн\w*\s+дискусси\w*|дискусси\w*|"
    r"если\s+ты\s+считаешь|моя\s+задача|уровень\s+коммуникаци\w*|"
    r"воспринимать\s+аргумент\w*|аргументаци\w*|оппонент\w*|"
    r"компетентн\w*\s+мнени\w*|переходи\s+к\s+обсуждени\w*|"
    r"по\s+существу\s+дела|акцент\w*\s+на|формулировк\w*\s+претензи\w*"
    r")\b",
    re.IGNORECASE,
)

_ULTRA_SHORT_REPLIES = (
    "Пошёл нахуй.",
    "Завали ебало.",
    "Иди лесом, душнила.",
    "Отъебись, интернет-боец.",
)

_ANTI_LECTURE_REPLIES = (
    "Ты тупой ишак, лови суть: хуйню сказал — хуйню получил. Пошёл нахуй.",
    "Слов дохуя, смысла на сдачу. Не души.",
    "О, профессор проснулся. Мысль сначала найди, потом выёбывайся.",
    "Не разводи кафедру в чате. Короче: хуйню сказал — получил ответ.",
    "И это всё, клоун? Теперь мысль попробуй родить.",
)

_COMPACT_SYSTEM_RULE = """
КРИТИЧЕСКОЕ ПРАВИЛО ДЛЯ ЭТОГО ОТВЕТА:
пользователь написал короткий наезд, подкол или претензию к манере речи.
Ответь ОДНОЙ-ДВУМЯ короткими фразами, максимум примерно 180 знаков.
Никаких объяснений, рассуждений, лекций, защиты своей позиции и повторения тезиса.
Не используй слова и обороты вроде «претензия», «аргументация», «оппонент»,
«конструктив», «дискуссия», «если ты считаешь», «моя задача», «по существу дела».
Это Telegram-перепалка, а не кафедра. Сразу дай короткий человеческий подкол и закончи.
Мат допустим, если он уже разрешён основными настройками персонажа.
""".strip()


def _should_force_compact(contents: Any) -> bool:
    text = content_to_text(contents).strip()

    if not text or len(text) > 260:
        return False
    if _SERIOUS_GUARD_RE.search(text):
        return False
    if _EXPLICIT_LONG_REQUEST_RE.search(text):
        return False

    return bool(_COMPACT_HOSTILE_RE.search(text))


def _clone_config_with_instruction(
    kwargs: dict[str, Any],
    extra_instruction: str,
    *,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    """Clone GenerateContentConfig and append a temporary system rule."""

    new_kwargs = dict(kwargs)
    config = new_kwargs.get("config")
    if config is None:
        return new_kwargs

    system_instruction = getattr(config, "system_instruction", None)
    if isinstance(system_instruction, str):
        new_system_instruction = system_instruction.rstrip() + "\n\n" + extra_instruction
    else:
        new_system_instruction = system_instruction

    updates: dict[str, Any] = {}
    if isinstance(new_system_instruction, str):
        updates["system_instruction"] = new_system_instruction

    if max_output_tokens is not None:
        current_max = getattr(config, "max_output_tokens", None)
        try:
            updates["max_output_tokens"] = min(int(current_max), max_output_tokens)
        except (TypeError, ValueError):
            updates["max_output_tokens"] = max_output_tokens

    try:
        if hasattr(config, "model_copy"):
            new_kwargs["config"] = config.model_copy(update=updates)
        else:
            for key, value in updates.items():
                setattr(config, key, value)
    except Exception as error:
        logging.debug("Gemini style guard: could not clone request config: %s", error)

    return new_kwargs


def _truncate_compact_text(text: str, max_chars: int = COMPACT_MAX_CHARS) -> str:
    clean = re.sub(r"\s+", " ", (text or "")).strip()
    if not clean:
        return clean

    # Roughly one reply out of three is deliberately a one-liner.
    if random.random() < 0.33:
        return random.choice(_ULTRA_SHORT_REPLIES)

    # Do not expose a clipped lecture; replace it completely.
    if _LECTURE_STYLE_RE.search(clean):
        return random.choice(_ANTI_LECTURE_REPLIES)

    sentences = re.split(r"(?<=[.!?…])\s+", clean)
    chosen: list[str] = []

    for sentence in sentences:
        candidate = " ".join(chosen + [sentence]).strip()
        if len(candidate) > max_chars:
            break
        chosen.append(sentence)
        if len(chosen) >= 2:
            break

    if chosen:
        compact = " ".join(chosen).strip()
        if compact:
            return compact

    if len(clean) <= max_chars:
        return clean

    cut = clean[: max_chars - 1].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0].rstrip()
    return cut.rstrip(" ,;:-") + "…"


class _CompactResponseProxy:
    def __init__(self, response: Any):
        self._response = response
        self._compact_text = _truncate_compact_text(
            getattr(response, "text", "") or ""
        )

    @property
    def text(self) -> str:
        return self._compact_text

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)


def _maybe_compact_response(response: Any, force_compact: bool) -> Any:
    if not force_compact:
        return response

    compact = _CompactResponseProxy(response)
    logging.info(
        "Gemini compact guard: output capped to %s chars (actual=%s)",
        COMPACT_MAX_CHARS,
        len(compact.text),
    )
    return compact


# ============================================================
# OPTIONAL GRAMMAR-NAZI MODE
# ============================================================

GRAMMAR_NAZI_CHANCE = 0.25

_GRAMMAR_NAZI_RULE = """
ДОПОЛНИТЕЛЬНЫЙ ВАРИАНТ ПОДКОЛА:
если в исходном сообщении пользователя действительно есть ЯВНАЯ орфографическая,
грамматическая или словарная ошибка, можешь сделать её главным коротким подколом.
Коротко укажи ошибочное слово/форму и правильный вариант, затем один панч.
Не превращай это в урок русского языка: максимум одна-две короткие фразы.
Если ошибки нет или ты не уверен на 100%, НИЧЕГО про грамотность не выдумывай
и отвечай как обычно. Не цепляйся к намеренному сленгу, мату, мемной орфографии,
опечатке из одной случайной клавиши или отсутствию знаков препинания.
""".strip()


def _should_offer_grammar_nazi(contents: Any) -> bool:
    text = content_to_text(contents).strip()

    if not text or len(text) > 240:
        return False
    if _SERIOUS_GUARD_RE.search(text):
        return False
    if _EXPLICIT_LONG_REQUEST_RE.search(text):
        return False
    if not re.search(r"[А-Яа-яЁё]{3,}", text):
        return False

    return random.random() < GRAMMAR_NAZI_CHANCE


# ============================================================
# TELEGRAM RATE-LIMIT MESSAGE STYLE
# ============================================================

_RATE_LIMIT_REPLIES = (
    "Не строчи, пулемётчик.",
    "Пальцы остуди, пулемётчик.",
    "Хватит спамить, автомат.",
)


def _install_rate_limit_reply_guard() -> None:
    """Hide the technical 'wait N seconds' text behind a character reply."""

    try:
        from telegram import Message
    except Exception as import_error:
        logging.warning("Rate-limit style guard unavailable: %s", import_error)
        return

    if getattr(Message.reply_text, "_yayceslav_rate_limit_guard", False):
        return

    original_reply_text = Message.reply_text

    async def styled_reply_text(self: Any, text: str, *args: Any, **kwargs: Any) -> Any:
        outgoing = text
        if (
            isinstance(text, str)
            and text.startswith("Полегче, пулемётчик.")
            and "Подожди примерно" in text
        ):
            outgoing = random.choice(_RATE_LIMIT_REPLIES)

        return await original_reply_text(self, outgoing, *args, **kwargs)

    styled_reply_text._yayceslav_rate_limit_guard = True
    Message.reply_text = styled_reply_text
    logging.warning("Rate-limit style guard installed: technical wait text hidden")


# ============================================================
# INSTALL GEMINI ROUTER / GUARDS
# ============================================================


def _install_gemini_router() -> None:
    global _primary_probe_in_progress

    try:
        from google.genai.models import AsyncModels
    except Exception as import_error:
        logging.error("Gemini router unavailable: %s", import_error)
        return

    if getattr(AsyncModels.generate_content, "_yayceslav_router_installed", False):
        return

    original_generate_content = AsyncModels.generate_content

    async def routed_generate_content(self: Any, *args: Any, **kwargs: Any) -> Any:
        global _primary_probe_in_progress

        requested_model = _requested_model(args, kwargs)

        # Only modify the main chat model. Explicit calls to other models pass through.
        if requested_model != PRIMARY_MODEL:
            return await original_generate_content(self, *args, **kwargs)

        contents = _request_contents(args, kwargs)
        force_compact = _should_force_compact(contents)
        grammar_nazi = _should_offer_grammar_nazi(contents)

        if force_compact:
            kwargs = _clone_config_with_instruction(
                kwargs,
                _COMPACT_SYSTEM_RULE,
                max_output_tokens=COMPACT_MAX_OUTPUT_TOKENS,
            )
            logging.info("Gemini compact guard active")

        if grammar_nazi:
            kwargs = _clone_config_with_instruction(
                kwargs,
                _GRAMMAR_NAZI_RULE,
            )
            logging.info("Gemini grammar-nazi option active")

        now = time.time()

        # Active cooldown: never waste a request on 3.6.
        if now < _primary_blocked_until_epoch:
            fallback_args, fallback_kwargs = _with_model(args, kwargs, FALLBACK_MODEL)
            logging.info(
                "Gemini router: 3.6 cooldown active (%.0fs left) -> 3.1",
                _primary_blocked_until_epoch - now,
            )
            result = await original_generate_content(
                self,
                *fallback_args,
                **fallback_kwargs,
            )
            return _maybe_compact_response(result, force_compact)

        recovering_from_cooldown = _primary_blocked_until_epoch > 0.0

        # After 30 minutes exactly one concurrent request probes 3.6.
        if recovering_from_cooldown:
            if _primary_probe_in_progress:
                fallback_args, fallback_kwargs = _with_model(args, kwargs, FALLBACK_MODEL)
                logging.info("Gemini router: 3.6 probe in flight -> 3.1")
                result = await original_generate_content(
                    self,
                    *fallback_args,
                    **fallback_kwargs,
                )
                return _maybe_compact_response(result, force_compact)

            _primary_probe_in_progress = True
            logging.warning("Gemini router: cooldown expired; probing 3.6")

        try:
            try:
                result = await original_generate_content(self, *args, **kwargs)
            except Exception as primary_error:
                if not _is_quota_429(primary_error):
                    raise

                _start_primary_cooldown()
                logging.warning(
                    "Gemini router: 3.6 returned 429 -> immediate 3.1; "
                    "next 3.6 probe in 30 minutes"
                )

                fallback_args, fallback_kwargs = _with_model(args, kwargs, FALLBACK_MODEL)
                result = await original_generate_content(
                    self,
                    *fallback_args,
                    **fallback_kwargs,
                )
                return _maybe_compact_response(result, force_compact)

            if recovering_from_cooldown:
                _clear_primary_cooldown()
                logging.warning("Gemini router: 3.6 probe succeeded; primary restored")

            return _maybe_compact_response(result, force_compact)
        finally:
            if recovering_from_cooldown:
                _primary_probe_in_progress = False

    routed_generate_content._yayceslav_router_installed = True
    AsyncModels.generate_content = routed_generate_content

    logging.warning(
        "Gemini router installed: 3.6 -> 3.1 on 429; retry 3.6 after 30 min"
    )
    logging.warning(
        "Gemini compact guard installed: hostile/challenge replies <= %s chars",
        COMPACT_MAX_CHARS,
    )
    logging.warning(
        "Gemini grammar-nazi option installed: %.0f%% chance on short non-serious text",
        GRAMMAR_NAZI_CHANCE * 100,
    )


_load_router_state()
_install_gemini_router()
_install_rate_limit_reply_guard()
