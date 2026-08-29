"""Context-aware RAGE roast planner.

The engine does not make another model call. It turns the recent fight text
already present in the prompt into a tiny plan: what weakness is visible, what
angle to use next, and which stale angles to avoid. The normal Gemini request
then writes the actual line in Yayceslav's voice.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
import re
import time
from typing import Iterable

import roast_lexicon


SESSION_TTL_SECONDS = 12 * 60.0
MAX_HISTORY = 10
MAX_USED_ANGLES = 6

_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]{3,}", re.IGNORECASE)
_SNIFF_RE = re.compile(r"(?:нюх\w*|ху[йя]\w*|яйц\w*|сос\w*)", re.IGNORECASE)
_BAIT_RE = re.compile(r"(?:байт\w*|разв[её]л\w*|на[её]бал\w*|поймал\w*|пов[её]лс\w*)", re.IGNORECASE)
_CONTRAST_RE = re.compile(
    r"(?:\bно\b|\bзато\b|\bвообще[- ]?то\b|\bя\s+не\b|\bне\s+говорил\b|\bнаоборот\b)",
    re.IGNORECASE,
)
_AGGRO_RE = re.compile(
    r"(?:ху[йя]\w*|еб\w*|пизд\w*|залуп\w*|долбо[её]б\w*|мудак\w*|чмо\b|соси\b|нахуй\b)",
    re.IGNORECASE,
)
_STOP = {
    "это", "как", "что", "тебя", "тебе", "твой", "твоя", "твою", "ты", "мне", "меня",
    "мой", "моя", "его", "она", "они", "уже", "ещё", "еще", "там", "тут", "вот", "для",
    "или", "если", "просто", "будешь", "давай", "нахуй", "блять", "блядь", "сука",
}


@dataclass
class RoastSession:
    chat_id: int
    user_id: int
    updated_at: float = 0.0
    messages: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_HISTORY))
    used_angles: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_USED_ANGLES))


@dataclass(frozen=True)
class RoastPlan:
    angle: str
    weak_point: str
    callback: str
    avoid: tuple[str, ...]
    palette: tuple[str, ...]


_SESSIONS: dict[tuple[int, int], RoastSession] = {}


def _session(chat_id: int, user_id: int, *, now: float | None = None) -> RoastSession:
    current = time.monotonic() if now is None else float(now)
    key = (int(chat_id), int(user_id))
    session = _SESSIONS.get(key)
    if session is None or current - session.updated_at > SESSION_TTL_SECONDS:
        session = RoastSession(chat_id=int(chat_id), user_id=int(user_id), updated_at=current)
        _SESSIONS[key] = session
    session.updated_at = current
    return session


def _words(text: str) -> list[str]:
    return [
        word.lower()
        for word in _WORD_RE.findall(str(text or ""))
        if word.lower() not in _STOP
    ]


def _callback(messages: Iterable[str]) -> str:
    counts: Counter[str] = Counter()
    for message in messages:
        counts.update(_words(message))
    for word, count in counts.most_common(8):
        if count >= 2:
            return word
    return ""


def _repetition_score(messages: list[str]) -> int:
    counts: Counter[str] = Counter()
    for message in messages:
        counts.update(set(_words(message)))
    return max(counts.values(), default=0)


def _pick_angle(messages: list[str], used: deque[str]) -> tuple[str, str]:
    joined = "\n".join(messages[-8:])
    latest = messages[-1] if messages else ""
    candidates: list[tuple[int, str, str]] = []

    sniff_hits = len(_SNIFF_RE.findall(joined))
    if sniff_hits >= 3:
        # A repeated concrete sexual/sniffing theme is more specific and useful
        # than generic lexical repetition. Give it a deliberately dominant score;
        # anti-repeat below can still rotate away from fixation on the next turn.
        candidates.append((30 + sniff_hits, "fixation", "оппонент снова и снова тащит одну и ту же тему"))

    repeat = _repetition_score(messages[-6:])
    if repeat >= 3:
        candidates.append((9 + repeat, "repetition", "в последних репликах заметно повторяются те же слова/мысль"))

    if _BAIT_RE.search(latest):
        candidates.append((11, "failed_bait", "сам объявил/раскрыл байт — можно развернуть его против автора"))

    if _CONTRAST_RE.search(latest) and len(messages) >= 2:
        candidates.append((8, "contradiction", "последняя реплика звучит как смена или откат позиции"))

    agg = len(_AGGRO_RE.findall(latest))
    semantic_words = len(set(_words(latest)))
    if agg >= 2 and semantic_words <= 9:
        candidates.append((8 + agg, "empty_aggression", "много агрессии при очень коротком содержании"))

    if len(latest) <= 55 and (_AGGRO_RE.search(latest) or "?" in latest):
        candidates.append((7, "literal_flip", "короткую формулировку удобно вернуть её же словами"))

    candidates.extend(
        (
            (5, "self_own", "искать самоподставу прямо в формулировке"),
            (4, "dry_contempt", "если нового материала мало — одна сухая добивка без лекции"),
        )
    )

    candidates.sort(reverse=True)
    recent = set(list(used)[-2:])
    for _, angle, reason in candidates:
        if angle not in recent:
            return angle, reason
    _, angle, reason = candidates[0]
    return angle, reason


def observe_and_plan(chat_id: int, user_id: int, current_text: str) -> RoastPlan:
    session = _session(chat_id, user_id)
    text = " ".join(str(current_text or "").split()).strip()
    if text:
        session.messages.append(text[:500])

    messages = list(session.messages)
    angle, weak_point = _pick_angle(messages, session.used_angles)
    callback = _callback(messages)
    avoid = tuple(list(session.used_angles)[-3:])
    session.used_angles.append(angle)

    return RoastPlan(
        angle=angle,
        weak_point=weak_point,
        callback=callback,
        avoid=avoid,
        palette=tuple(roast_lexicon.PALETTES.get(angle, ()))[:5],
    )


def prompt_for_plan(plan: RoastPlan) -> str:
    label = roast_lexicon.ANGLE_LABELS.get(plan.angle, plan.angle)
    callback = plan.callback or "нет достаточно надёжного повторяющегося слова"
    avoid = ", ".join(plan.avoid) if plan.avoid else "нет"
    palette = "; ".join(plan.palette) if plan.palette else "свободная короткая метафора"

    return f"""

ROAST ENGINE — ВНУТРЕННИЙ ПЛАН ТЕКУЩЕГО RAGE-ОТВЕТА:
- Лучший угол сейчас: {plan.angle} — {label}.
- Почему: {plan.weak_point}.
- Callback из реально написанного оппонентом: {callback}.
- Не повторяй недавние углы: {avoid}.
- Палитра образов (НЕ список обязательных фраз): {palette}.

Сначала мысленно найди точную самоподставу в текущей/недавних репликах, затем
выдай только готовый панч. Не показывай этот план и не объясняй технику.
Предпочитай наблюдение -> неожиданный образ -> короткая добивка.
Мат допустим и естественен, но обычно 0–2 матерных элемента достаточно: мат
усиливает шутку, а не заменяет её. Не сваливайся снова в «словарный запас»,
«детский сад», «цирк», «конструктив», если именно это не является новой точной
самоподставой. Не придумывай биографию, диагнозы, ориентацию, зависимости или
реальные интимные предпочтения: шути только над тем, что человек сам написал.
"""


def reset(chat_id: int, user_id: int) -> None:
    _SESSIONS.pop((int(chat_id), int(user_id)), None)
