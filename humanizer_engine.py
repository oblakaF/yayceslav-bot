from __future__ import annotations

import random
import re
from dataclasses import dataclass

import personality


SPLIT_CHANCE = 0.08
CONFLICT_TWO_MESSAGE_CHANCE = 0.38
TYPO_CHANCE = 0.012
LAZY_SHORT_CHANCE = 0.004
LAZY_REFUSAL_CHANCE = 0.0008

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?…])\s+")
_CYRILLIC_WORD_RE = re.compile(r"\b[а-яё]{5,12}\b", re.IGNORECASE)

# Strong insults/commands are conflict even without an explicit "ты".
# Word stems deliberately cover common declined/derived forms.
_STRONG_CONFLICT_RE = re.compile(
    r"(?:"
    r"\b(?:"
    r"сука|сучка|еблан\w*|долбо[её]б\w*|у[её]бок\w*|"
    r"мудак\w*|мудач\w*|мудил\w*|чмо|мраз\w*|гнид\w*|"
    r"ублюд\w*|падл\w*|сволоч\w*|говнюк\w*|говноед\w*|"
    r"дебил\w*|идиот\w*|кретин\w*|придур\w*|недоум\w*|"
    r"имбецил\w*|тупорыл\w*|безмозгл\w*|псин\w*|шавк\w*|"
    r"пиздабол\w*|заебал\w*"
    r")\b|"
    r"\b(?:нахуй|на\s+хуй)\b|"
    r"\b(?:отъеб\w*|съеб\w*)\b|"
    r"\b(?:иди|пош[её]л)\s+(?:нахуй|на\s+хуй|в\s+пизду)\b|"
    r"\b(?:завали|закрой)\s+ебало\b|"
    r"\bебало\s+(?:завали|закрой)\b|"
    r"\bхуй\s+соси\b"
    r")",
    re.IGNORECASE,
)

# These words are ambiguous in ordinary Russian. They count as an insult only
# when directed at the interlocutor, or when the whole message is the insult.
_AMBIGUOUS_INSULT = (
    r"(?:клоун\w*|баран\w*|ос[её]л\w*|коз[её]л\w*|собак\w*|"
    r"крыс\w*|свин\w*|петух\w*|обезьян\w*|скуф\w*|"
    r"нищ\w*|бомж\w*|днищ\w*|позорищ\w*|ничтож\w*|"
    r"жалк\w*|никч[её]мн\w*|тормоз\w*)"
)
_DIRECTED_AMBIGUOUS_CONFLICT_RE = re.compile(
    rf"(?:"
    rf"\b(?:ты|тебя|тебе|твой|твоя|тво[её]|твои)\b.{{0,28}}\b{_AMBIGUOUS_INSULT}\b|"
    rf"\b{_AMBIGUOUS_INSULT}\b.{{0,20}}\b(?:ты|тебя|тебе)\b|"
    rf"\bну\s+ты\s+и\s+{_AMBIGUOUS_INSULT}\b|"
    rf"^\s*{_AMBIGUOUS_INSULT}\s*[!?.]*\s*$"
    rf")",
    re.IGNORECASE | re.DOTALL,
)

# Tone complaints are also kept compact even though they are not necessarily insults.
_CONFLICT_STYLE_COMPLAINT_RE = re.compile(
    r"(?:"
    r"\bдушн\w*\b|"
    r"\bпростын\w*\b|"
    r"много\s+текста|слишком\s+длинн\w*|короче\s+отвечай|не\s+пиши\s+столько"
    r")",
    re.IGNORECASE,
)


def _install_personality_hostile_extension() -> None:
    """Make the main conversation-mode classifier use the same insult lexicon."""

    current = personality.HOSTILE_RE
    if getattr(current, "_yayceslav_extended_hostile", False):
        return

    combined = re.compile(
        rf"(?:{current.pattern}|{_STRONG_CONFLICT_RE.pattern}|"
        rf"{_DIRECTED_AMBIGUOUS_CONFLICT_RE.pattern})",
        re.IGNORECASE | re.DOTALL,
    )
    # re.Pattern objects do not allow arbitrary attributes, so idempotence is
    # recorded on the personality module instead.
    personality.HOSTILE_RE = combined
    personality._YAYCESLAV_EXTENDED_HOSTILE = True


# bot.py imports humanizer_engine before it imports HOSTILE_RE and
# detect_conversation_mode from personality, so this extends the central
# classifier without duplicating or rewriting personality.py.
if not getattr(personality, "_YAYCESLAV_EXTENDED_HOSTILE", False):
    _install_personality_hostile_extension()


_IMPORTANT_INTENTS = {
    "technical_help",
    "factual_lookup",
    "recommendation",
    "serious_issue",
    "emotional_support",
    "request",
}

_IMPORTANT_MARKERS = (
    "объясни",
    "почему",
    "как сделать",
    "как работает",
    "помоги",
    "ошибка",
    "код",
    "документ",
    "файл",
    "деньги",
    "здоров",
    "врач",
    "лекар",
    "право",
    "срочно",
    "найди",
    "проверь",
    "сравни",
    "проанализируй",
)


@dataclass(frozen=True)
class HumanizedReply:
    messages: tuple[str, ...]
    delays: tuple[float, ...]
    effect: str = "none"


def _eligible_group_chat(trace) -> bool:
    return bool(
        trace
        and getattr(trace, "chat_type", "") in {"group", "supergroup"}
        and not getattr(trace, "serious_topic", False)
        and getattr(trace, "conversation_mode", "normal") != "serious"
    )


def _important_request(user_text: str, trace) -> bool:
    intent = getattr(trace, "message_intent", "unknown") if trace else "unknown"
    if intent in _IMPORTANT_INTENTS:
        return True
    lowered = (user_text or "").lower()
    if len(lowered) >= 160:
        return True
    return any(marker in lowered for marker in _IMPORTANT_MARKERS)


def _looks_like_conflict(user_text: str) -> bool:
    text = user_text or ""
    return bool(
        _STRONG_CONFLICT_RE.search(text)
        or _DIRECTED_AMBIGUOUS_CONFLICT_RE.search(text)
        or _CONFLICT_STYLE_COMPLAINT_RE.search(text)
    )


def _lazy_eligible_request(user_text: str, trace) -> bool:
    if _looks_like_conflict(user_text):
        return False
    intent_name = getattr(trace, "message_intent", "unknown") if trace else "unknown"
    # "Лень" — редкий прикол только на реальном простом вопросе,
    # а не на междометии, оскорблении или обычной реплике чата.
    return intent_name == "question" and len((user_text or "").strip()) <= 120


def _first_compact_sentence(text: str, limit: int = 190) -> str:
    text = " ".join((text or "").split())
    if not text:
        return ""
    parts = _SENTENCE_BOUNDARY_RE.split(text, maxsplit=1)
    first = parts[0].strip()
    if len(first) <= limit:
        return first
    clipped = first[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return clipped + "…"


def _compact_conflict_text(
    text: str,
    *,
    max_chars: int,
    max_sentences: int = 2,
) -> tuple[str, ...]:
    clean = " ".join((text or "").split())
    if not clean:
        return ("",)

    sentences = [part.strip() for part in _SENTENCE_BOUNDARY_RE.split(clean) if part.strip()]
    if not sentences:
        sentences = [clean]

    # A short explicit send-off is already a complete human reply.
    # Do not append Gemini's explanatory second sentence after it.
    first_lower = sentences[0].lower()
    direct_sendoff_markers = (
        "иди нах",
        "пошел нах",
        "пошёл нах",
        "нахуй",
        "на хуй",
        "отъеб",
        "съеб",
        "завали ебало",
    )
    if (
        len(sentences[0]) <= 45
        and any(marker in first_lower for marker in direct_sendoff_markers)
    ):
        return (sentences[0],)

    kept: list[str] = []
    total = 0
    for sentence in sentences[:max_sentences]:
        projected = total + (1 if kept else 0) + len(sentence)
        if projected <= max_chars:
            kept.append(sentence)
            total = projected
            continue
        if not kept:
            clipped = sentence[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:-")
            kept.append((clipped or sentence[:max_chars]).rstrip() + "…")
        break

    return tuple(kept or [clean[:max_chars]])


def _split_naturally(text: str) -> tuple[str, str] | None:
    if len(text) < 120 or len(text) > 850:
        return None
    if "```" in text or "http://" in text or "https://" in text:
        return None

    matches = list(_SENTENCE_BOUNDARY_RE.finditer(text))
    if not matches:
        return None

    target = len(text) * 0.52
    match = min(matches, key=lambda item: abs(item.start() - target))
    first = text[: match.start()].strip()
    second = text[match.end() :].strip()
    if len(first) < 45 or len(second) < 35:
        return None
    return first, second


def _make_typo(text: str, *, rng=random) -> tuple[str, str] | None:
    candidates = [
        match
        for match in _CYRILLIC_WORD_RE.finditer(text)
        if match.group(0).islower()
    ]
    if not candidates:
        return None

    match = rng.choice(candidates)
    word = match.group(0)
    if len(set(word)) < 3:
        return None

    indexes = [i for i in range(1, len(word) - 2) if word[i] != word[i + 1]]
    if not indexes:
        return None
    index = rng.choice(indexes)
    typo = word[:index] + word[index + 1] + word[index] + word[index + 2 :]
    changed = text[: match.start()] + typo + text[match.end() :]
    return changed, "*" + word


def humanize_reply(
    text: str,
    *,
    user_text: str = "",
    trace=None,
    hostile_streak: int = 0,
    rng=random,
) -> HumanizedReply:
    """Применяет максимум один человеческий эффект за ответ."""

    clean = (text or "").strip()
    if not clean or not _eligible_group_chat(trace):
        return HumanizedReply((clean,), (0.0,))

    important = _important_request(user_text, trace)
    mode = getattr(trace, "conversation_mode", "normal") if trace else "normal"

    # Conflict rhythm is enforced after Gemini, not merely requested in the prompt.
    # Any non-serious hostile/challenge turn stays compact. Repeated hostility may
    # change wording/intensity elsewhere, but it must never unlock a text wall.
    raw_conflict = _looks_like_conflict(user_text)
    compact_conflict = raw_conflict or mode in {"challenge", "hostile"}
    if compact_conflict and not important:
        max_chars = 95 if (raw_conflict or mode == "hostile") else 110
        max_sentences = 2
        pieces = _compact_conflict_text(
            clean,
            max_chars=max_chars,
            max_sentences=max_sentences,
        )
        compact = " ".join(pieces).strip()
        if len(pieces) >= 2 and rng.random() < CONFLICT_TWO_MESSAGE_CHANCE:
            return HumanizedReply(
                (pieces[0], pieces[1]),
                (0.0, rng.uniform(0.65, 1.55)),
                "conflict_split",
            )
        return HumanizedReply((compact,), (0.0,), "conflict_compact")

    if not important and _lazy_eligible_request(user_text, trace):
        roll = rng.random()
        if roll < LAZY_REFUSAL_CHANCE:
            return HumanizedReply(("бля лень. гугл есть.",), (0.0,), "lazy_refusal")
        if roll < LAZY_REFUSAL_CHANCE + LAZY_SHORT_CHANCE:
            short = _first_compact_sentence(clean)
            if short:
                return HumanizedReply(("бля лень расписывать. короче: " + short,), (0.0,), "lazy_short")

    if rng.random() < TYPO_CHANCE:
        typo = _make_typo(clean, rng=rng)
        if typo:
            changed, correction = typo
            return HumanizedReply(
                (changed, correction),
                (0.0, rng.uniform(0.55, 1.45)),
                "typo_correction",
            )

    if rng.random() < SPLIT_CHANCE:
        split = _split_naturally(clean)
        if split:
            first, second = split
            return HumanizedReply(
                (first, second),
                (0.0, rng.uniform(0.7, 2.4)),
                "split",
            )

    return HumanizedReply((clean,), (0.0,))