# ============================================================
# YAICESLAV V2 — DYNAMIC GEMINI THINKING POLICY
#
# Gemini 3.6 Flash supports: minimal / low / medium / high.
# The bot should not spend medium reasoning on every casual message.
# ============================================================

from __future__ import annotations

import re
from typing import Any


THINKING_MINIMAL = "minimal"
THINKING_LOW = "low"
THINKING_MEDIUM = "medium"

SUPPORTED_LEVELS = {
    THINKING_MINIMAL,
    THINKING_LOW,
    THINKING_MEDIUM,
    "high",
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
    r"что\s+думаешь|как\s+считаешь|зачем|стоит\s+ли)\b",
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
    """Extract only useful textual content for the thinking policy."""

    if isinstance(contents, str):
        return contents

    if isinstance(contents, (list, tuple)):
        parts: list[str] = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)

    return ""


def choose_thinking_level(
    contents: Any,
    *,
    explicit: str | None = None,
) -> str:
    """
    Choose latency/quality balance for Gemini 3.6 Flash.

    Rules:
    - explicit validated level always wins;
    - search/analysis/debate/explicit explanation => medium;
    - short casual/banter/simple style tasks => minimal;
    - ordinary substantive chat => low.
    """

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
        return (
            THINKING_MEDIUM
            if len(text) >= 320
            else THINKING_LOW
        )

    words = re.findall(r"[\wёЁ]+", text, flags=re.UNICODE)

    if len(text) <= 120 and len(words) <= 18:
        return THINKING_MINIMAL

    if _CASUAL_RE.search(text) and len(text) <= 220:
        return THINKING_MINIMAL

    return THINKING_LOW
