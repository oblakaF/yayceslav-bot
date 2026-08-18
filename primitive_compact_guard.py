from __future__ import annotations

import logging
import re
from typing import Any


PRIMITIVE_MAX_CHARS = 110
PRIMITIVE_MAX_OUTPUT_TOKENS = 96

_TARGET_MODELS = {
    "gemini-3.6-flash",
    "gemini-3.1-flash-lite",
}

_GROUP_LAST_MESSAGE_RE = re.compile(
    r"Новое\s+обращение\s+к\s+тебе\s+от\s+[^:\n]+:\s*\n",
    re.IGNORECASE,
)
_PRIVATE_LAST_MESSAGE_RE = re.compile(
    r"Новое\s+сообщение\s+пользователя:\s*\n",
    re.IGNORECASE,
)

_SERIOUS_RE = re.compile(
    r"\b(?:"
    r"врач\w*|лекарств\w*|болит|болят|боль|симптом\w*|болезн\w*|"
    r"суицид\w*|умер\w*|смерт\w*|травм\w*|кровотеч\w*|насили\w*|"
    r"кредит\w*|долг\w*|пожар\w*"
    r")\b",
    re.IGNORECASE,
)

_EXPLICIT_LONG_RE = re.compile(
    r"\b(?:"
    r"объясни\w*|разъясни\w*|расскажи\w*|разбери\w*|подробн\w*|"
    r"проанализир\w*|анализ\w*|сравни\w*|докажи\w*|обоснуй\w*|"
    r"по\s+шагам|пошагов\w*"
    r")\b",
    re.IGNORECASE,
)

_SIMPLE_ARITHMETIC_RE = re.compile(
    r"^\s*(?:сколько\s+(?:будет\s+)?)?"
    r"[\d\s.,()+\-*/×÷%^]+[=?]?\s*$",
    re.IGNORECASE,
)

_SHORT_INTERJECTION_RE = re.compile(
    r"^\s*(?:"
    r"э+|эм+|м+|мм+|а+|ну|ага|угу|ок(?:ей)?|ладно|"
    r"ч[её]|что|хм+|лол|кек|ау|ал[её]|ясно|понятно"
    r")[.!?,…\s]*$",
    re.IGNORECASE,
)

_PRIMITIVE_RULE = """
КРИТИЧЕСКОЕ ПРАВИЛО ДЛЯ ЭТОГО ОТВЕТА:
последнее сообщение пользователя примитивное и короткое: простая арифметика
или одно короткое междометие/реплика. Не разводи стендап, лекцию или два абзаца.
Дай правильный ответ сразу и, если уместно, максимум ОДИН короткий подкол.
Итог: одна-две очень короткие фразы, желательно до 110 знаков.
Для арифметики сначала обязательно дай само число/результат.
Для «э», «ну», «чё» и похожих реплик ответь коротко по-человечески.
Не придумывай длинный сюжет, не объясняй очевидное и не повторяй мысль разными словами.
""".strip()


def _content_to_text(contents: Any) -> str:
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
                continue
            item_parts = getattr(item, "parts", None)
            if isinstance(item_parts, (list, tuple)):
                for part in item_parts:
                    part_text = getattr(part, "text", None)
                    if isinstance(part_text, str):
                        parts.append(part_text)
        return "\n".join(parts)

    text = getattr(contents, "text", None)
    return text if isinstance(text, str) else ""


def latest_user_text(contents: Any) -> str:
    text = _content_to_text(contents).strip()
    if not text:
        return ""

    matches = list(_GROUP_LAST_MESSAGE_RE.finditer(text))
    matches.extend(_PRIVATE_LAST_MESSAGE_RE.finditer(text))
    if matches:
        last = max(matches, key=lambda match: match.start())
        return text[last.end():].strip()

    return text


def is_simple_arithmetic(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped or len(stripped) > 48:
        return False
    if not _SIMPLE_ARITHMETIC_RE.fullmatch(stripped):
        return False
    # A bare number/date is not enough. Require an actual arithmetic operator.
    return bool(re.search(r"[+*/×÷%^]", stripped) or re.search(r"\d\s*-\s*\d", stripped))


def should_force_primitive_compact(contents: Any) -> bool:
    text = latest_user_text(contents).strip()
    if not text or len(text) > 80:
        return False
    if _SERIOUS_RE.search(text) or _EXPLICIT_LONG_RE.search(text):
        return False
    return is_simple_arithmetic(text) or bool(_SHORT_INTERJECTION_RE.fullmatch(text))


def _requested_model(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    if "model" in kwargs:
        value = kwargs.get("model")
        return str(value) if value is not None else None
    if args:
        return str(args[0])
    return None


def _request_contents(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if "contents" in kwargs:
        return kwargs.get("contents")
    if len(args) >= 2:
        return args[1]
    return None


def _clone_config(kwargs: dict[str, Any]) -> dict[str, Any]:
    new_kwargs = dict(kwargs)
    config = new_kwargs.get("config")
    if config is None:
        return new_kwargs

    system_instruction = getattr(config, "system_instruction", None)
    if isinstance(system_instruction, str):
        new_instruction = system_instruction.rstrip() + "\n\n" + _PRIMITIVE_RULE
    else:
        new_instruction = system_instruction

    updates: dict[str, Any] = {}
    if isinstance(new_instruction, str):
        updates["system_instruction"] = new_instruction

    current_max = getattr(config, "max_output_tokens", None)
    try:
        updates["max_output_tokens"] = min(int(current_max), PRIMITIVE_MAX_OUTPUT_TOKENS)
    except (TypeError, ValueError):
        updates["max_output_tokens"] = PRIMITIVE_MAX_OUTPUT_TOKENS

    try:
        if hasattr(config, "model_copy"):
            new_kwargs["config"] = config.model_copy(update=updates)
        else:
            for key, value in updates.items():
                setattr(config, key, value)
    except Exception as error:
        logging.debug("Primitive compact guard: could not clone config: %s", error)

    return new_kwargs


def truncate_primitive_text(text: str, max_chars: int = PRIMITIVE_MAX_CHARS) -> str:
    clean = re.sub(r"\s+", " ", (text or "")).strip()
    if not clean:
        return clean

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


class _PrimitiveResponseProxy:
    def __init__(self, response: Any):
        self._response = response
        self._text = truncate_primitive_text(getattr(response, "text", "") or "")

    @property
    def text(self) -> str:
        return self._text

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)


def install_primitive_compact_guard() -> None:
    try:
        from google.genai.models import AsyncModels
    except Exception as import_error:
        logging.warning("Primitive compact guard unavailable: %s", import_error)
        return

    if getattr(AsyncModels.generate_content, "_yayceslav_primitive_guard", False):
        return

    original_generate_content = AsyncModels.generate_content

    async def guarded_generate_content(self: Any, *args: Any, **kwargs: Any) -> Any:
        requested_model = _requested_model(args, kwargs)
        if requested_model not in _TARGET_MODELS:
            return await original_generate_content(self, *args, **kwargs)

        contents = _request_contents(args, kwargs)
        force_compact = should_force_primitive_compact(contents)
        if force_compact:
            kwargs = _clone_config(kwargs)
            logging.info(
                "Primitive compact guard active: input=%r",
                latest_user_text(contents)[:80],
            )

        result = await original_generate_content(self, *args, **kwargs)
        if not force_compact:
            return result

        compact = _PrimitiveResponseProxy(result)
        logging.info(
            "Primitive compact guard: output <=%s chars (actual=%s)",
            PRIMITIVE_MAX_CHARS,
            len(compact.text),
        )
        return compact

    guarded_generate_content._yayceslav_primitive_guard = True
    AsyncModels.generate_content = guarded_generate_content
    logging.warning(
        "Primitive compact guard installed: arithmetic/interjections <= %s chars",
        PRIMITIVE_MAX_CHARS,
    )


install_primitive_compact_guard()
