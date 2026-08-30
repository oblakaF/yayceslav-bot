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
MAX_USED_HOOKS = 6

_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]{3,}", re.IGNORECASE)
_SNIFF_RE = re.compile(r"(?:нюх\w*|ху[йя]\w*|яйц\w*|сос\w*)", re.IGNORECASE)
_BAIT_RE = re.compile(r"(?:байт\w*|разв[её]л\w*|на[её]бал\w*|поймал\w*|пов[её]лс\w*)", re.IGNORECASE)
_CONTRAST_RE = re.compile(
    r"(?:\bно\b|\bзато\b|\bвообще[- ]?то\b|\bя\s+не\b|\bне\s+говорил\b|\bнаоборот\b)",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(r"(?:^|\s)(?:не|нет|никогда|ничего|ни\s+разу)(?:\s|$)", re.IGNORECASE)
_EXIT_RE = re.compile(
    r"(?:\bвс[её]\b.{0,18}\b(?:ухожу|уш[её]л|сваливаю|пош[её]л)\b|"
    r"\bбольше\s+не\s+(?:пиш\w*|отвеч\w*)|"
    r"\bне\s+буду\s+(?:пиш\w*|отвеч\w*))",
    re.IGNORECASE,
)
_INDIFFERENCE_RE = re.compile(
    r"(?:\bмне\s+(?:похуй|плевать|по\s*херу|вс[её]\s+равно)\b|\bмне\s+не\s+интересно\b)",
    re.IGNORECASE,
)
_CALM_CLAIM_RE = re.compile(
    r"(?:\bя\s+споко(?:ен|йна)\b|\bменя\s+не\s+бомбит\b|\bу\s+меня\s+не\s+горит\b)",
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
    used_hooks: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_USED_HOOKS))


@dataclass(frozen=True)
class ObservedHook:
    kind: str
    reason: str
    evidence: tuple[str, ...]
    score: int
    signature: str


@dataclass(frozen=True)
class RoastPlan:
    angle: str
    weak_point: str
    callback: str
    avoid: tuple[str, ...]
    palette: tuple[str, ...]
    evidence: tuple[str, ...] = ()
    focus_kind: str = ""
    focus_reason: str = ""
    focus_evidence: tuple[str, ...] = ()


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


def _evidence(messages: list[str]) -> tuple[str, ...]:
    """Keep a tiny verbatim window so Gemini attacks observed wording, not biography."""
    compact: list[str] = []
    for message in messages[-4:]:
        text = " ".join(str(message or "").split()).strip()
        if text and text not in compact:
            compact.append(text[:180])
    return tuple(compact)


def _repetition_score(messages: list[str]) -> int:
    counts: Counter[str] = Counter()
    for message in messages:
        counts.update(set(_words(message)))
    return max(counts.values(), default=0)


def _hook_signature(kind: str, evidence: tuple[str, ...]) -> str:
    normalized = "|".join(" ".join(item.lower().split()) for item in evidence)
    return f"{kind}:{normalized[:360]}"


def _has_negation(text: str) -> bool:
    normalized = f" {' '.join(str(text or '').lower().split())} "
    return bool(_NEGATION_RE.search(normalized))


def _contradiction_hooks(messages: list[str]) -> list[ObservedHook]:
    """Find high-precision wording flips: same proposition, opposite negation."""
    window = messages[-6:]
    hooks: list[ObservedHook] = []
    for later_index in range(1, len(window)):
        later = window[later_index]
        later_terms = set(_words(later))
        if not later_terms:
            continue
        later_negated = _has_negation(later)
        for earlier_index in range(later_index):
            earlier = window[earlier_index]
            if _has_negation(earlier) == later_negated:
                continue
            earlier_terms = set(_words(earlier))
            if not earlier_terms:
                continue
            shared = earlier_terms & later_terms
            smaller = min(len(earlier_terms), len(later_terms))
            coverage = len(shared) / max(1, smaller)
            strong_single = (
                len(shared) == 1
                and len(next(iter(shared))) >= 5
                and smaller <= 2
                and coverage >= 0.5
            )
            if not ((len(shared) >= 2 and coverage >= 0.5) or strong_single):
                continue
            evidence = (earlier[:180], later[:180])
            score = 80 + min(12, len(shared) * 3) + later_index
            hooks.append(
                ObservedHook(
                    kind="contradiction",
                    reason="две собственные реплики сохраняют одну формулировку, но меняют отрицание",
                    evidence=evidence,
                    score=score,
                    signature=_hook_signature("contradiction", evidence),
                )
            )
    return hooks


def _self_own_hooks(messages: list[str]) -> list[ObservedHook]:
    """Find sequence-level self-owns that are visible without guessing motives."""
    window = messages[-6:]
    hooks: list[ObservedHook] = []
    for earlier_index, earlier in enumerate(window[:-1]):
        later_messages = window[earlier_index + 1 :]
        if not later_messages:
            continue
        latest = later_messages[-1]

        if _EXIT_RE.search(earlier):
            evidence = (earlier[:180], latest[:180])
            hooks.append(
                ObservedHook(
                    kind="self_own",
                    reason="сам объявил, что уходит/не отвечает, а затем снова написал",
                    evidence=evidence,
                    score=96 + earlier_index,
                    signature=_hook_signature("self_own_exit", evidence),
                )
            )

        if _INDIFFERENCE_RE.search(earlier):
            continued_hard = any(_AGGRO_RE.search(item) for item in later_messages)
            if continued_hard or len(later_messages) >= 2:
                evidence = (earlier[:180], latest[:180])
                hooks.append(
                    ObservedHook(
                        kind="self_own",
                        reason="сам заявил, что ему всё равно, но продолжил тот же горячий спор",
                        evidence=evidence,
                        score=88 + earlier_index + (4 if continued_hard else 0),
                        signature=_hook_signature("self_own_indifference", evidence),
                    )
                )

        if _CALM_CLAIM_RE.search(earlier):
            aggressive_later = next((item for item in reversed(later_messages) if len(_AGGRO_RE.findall(item)) >= 2), "")
            if aggressive_later:
                evidence = (earlier[:180], aggressive_later[:180])
                hooks.append(
                    ObservedHook(
                        kind="self_own",
                        reason="сначала прямо назвал себя спокойным, затем сам же написал реплику с несколькими оскорблениями",
                        evidence=evidence,
                        score=82 + earlier_index,
                        signature=_hook_signature("self_own_calm", evidence),
                    )
                )
    return hooks


def _select_focus(messages: list[str], used_hooks: deque[str]) -> ObservedHook | None:
    candidates = _self_own_hooks(messages) + _contradiction_hooks(messages)
    if not candidates:
        return None
    used = set(used_hooks)
    fresh = [candidate for candidate in candidates if candidate.signature not in used]
    if not fresh:
        return None
    fresh.sort(key=lambda candidate: candidate.score, reverse=True)
    return fresh[0]


def _pick_angle(messages: list[str], used: deque[str], focus: ObservedHook | None = None) -> tuple[str, str]:
    if focus is not None:
        # A fresh, grounded hook is more valuable than generic angle rotation.
        return focus.kind, focus.reason

    joined = "\n".join(messages[-8:])
    latest = messages[-1] if messages else ""
    candidates: list[tuple[int, str, str]] = []

    sniff_hits = len(_SNIFF_RE.findall(joined))
    if sniff_hits >= 3:
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
    focus = _select_focus(messages, session.used_hooks)
    angle, weak_point = _pick_angle(messages, session.used_angles, focus)
    callback = _callback(messages)
    avoid = tuple(list(session.used_angles)[-3:])
    session.used_angles.append(angle)
    if focus is not None:
        session.used_hooks.append(focus.signature)

    return RoastPlan(
        angle=angle,
        weak_point=weak_point,
        callback=callback,
        avoid=avoid,
        palette=tuple(roast_lexicon.PALETTES.get(angle, ()))[:5],
        evidence=_evidence(messages),
        focus_kind=focus.kind if focus is not None else "",
        focus_reason=focus.reason if focus is not None else "",
        focus_evidence=focus.evidence if focus is not None else (),
    )


def prompt_for_plan(plan: RoastPlan) -> str:
    label = roast_lexicon.ANGLE_LABELS.get(plan.angle, plan.angle)
    callback = plan.callback or "нет достаточно надёжного повторяющегося слова"
    avoid = ", ".join(plan.avoid) if plan.avoid else "нет"
    palette = "; ".join(plan.palette) if plan.palette else "свободная короткая метафора"
    evidence = " | ".join(f"«{item}»" for item in plan.evidence) or "нет"
    if plan.focus_kind and plan.focus_evidence:
        focus = (
            f"{plan.focus_kind}: {plan.focus_reason}; "
            + " <-> ".join(f"«{item}»" for item in plan.focus_evidence)
        )
    else:
        focus = "нет отдельного проверенного межрепличного крючка"

    return f"""

ROAST ENGINE V3 — ВНУТРЕННИЙ ПЛАН ТЕКУЩЕГО RAGE-ОТВЕТА:
- Лучший угол сейчас: {plan.angle} — {label}.
- Почему: {plan.weak_point}.
- Проверенный self-own/contradiction hook: {focus}.
- Callback из реально написанного оппонентом: {callback}.
- Последние точные реплики оппонента: {evidence}.
- Не повторяй недавние углы: {avoid}.
- Палитра образов (НЕ список обязательных фраз): {palette}.

Если указан проверенный hook, он приоритетнее общего оскорбления: столкни именно
эти две наблюдаемые реплики и добей противоречие/самоподставу. Не достраивай
мотивы. Не объявляй противоречием то, чего буквально не видно в приведённых
строках; если hook не подходит к текущей реплике, используй следующий grounded
угол из плана.

Сначала мысленно найди ОДНУ точную самоподставу в приведённых репликах. Затем
собери панч: конкретное наблюдение -> неожиданный образ/сравнение -> короткая
добивка. Выдай только готовый ответ, без разбора техники.

КРИТЕРИЙ КАЧЕСТВА: ответ должен быть смешным даже без мата. Если убрать мат и
останется только «ты тупой/у тебя мало слов/у тебя комплексы», придумай заново.
Не используй дежурные мета-оскорбления про словарный запас, детский сад, цирк,
конструктив, комплексы, фантазёра или альфа-самца, если это не буквальная новая
самоподстава текущей реплики. Не пересказывай мораль и не объясняй оппоненту его
психологию.

Обычно 1–2 коротких предложения. Мат допустим и естественен, но обычно 0–2
матерных элемента достаточно: он усиливает шутку, а не заменяет её. Можно
вернуть точное слово/формулировку оппонента, особенно если он её повторяет.
Не придумывай биографию, диагнозы, ориентацию, зависимости или реальные
интимные предпочтения: шути только над наблюдаемым поведением и тем, что человек
сам написал. Гиперболическая псевдонаучная метафора допустима только как явно
комическая метафора поведения, а не как утверждение реального диагноза.
"""


def reset(chat_id: int, user_id: int) -> None:
    _SESSIONS.pop((int(chat_id), int(user_id)), None)
