from __future__ import annotations

import math
import re
from collections.abc import Iterable

PACK_NAME = "chat_native"
PROFILE_REFRESH_SECONDS = 7 * 24 * 60 * 60
INITIAL_MIN_DISTINCT_USERS = 3
INITIAL_MIN_SELECTED_TERMS = 4
MAX_PROFILE_TERMS = 24

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b\S+@\S+\.\S+\b")
_MENTION_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{3,}")
_COMMAND_RE = re.compile(r"(?<!\w)/[A-Za-zА-Яа-яЁё0-9_]+")
_TOKEN_RE = re.compile(r"[a-zа-яё][a-zа-яё'’-]{2,23}", re.IGNORECASE)

_STOPWORDS = frozenset(
    {
        "это", "этот", "эта", "эти", "того", "тому", "тут", "там", "вот",
        "как", "что", "кто", "где", "когда", "зачем", "почему", "какой",
        "какая", "какие", "какое", "так", "такой", "такая", "такие", "очень",
        "просто", "вообще", "тоже", "уже", "еще", "ещё", "только", "даже",
        "если", "или", "либо", "потому", "поэтому", "который", "которая",
        "которые", "которое", "чтобы", "будет", "было", "были", "есть", "нет",
        "для", "про", "при", "под", "над", "без", "между", "через", "после",
        "перед", "из-за", "меня", "тебя", "себя", "него", "нее", "неё", "них",
        "мой", "моя", "мои", "твой", "твоя", "твои", "наш", "ваш", "они", "она",
        "оно", "ему", "ей", "им", "мы", "вы", "ты", "он", "я", "мне", "нам",
        "вам", "был", "была", "быть", "буду", "будешь", "можно", "надо", "нужно",
        "хочу", "хочешь", "сейчас", "сегодня", "вчера", "завтра", "короче", "ладно",
        "ну", "да", "ага", "угу", "не", "ни", "же", "бы", "то", "ли", "а", "и",
        "но", "на", "в", "во", "к", "ко", "с", "со", "у", "о", "об", "от", "до",
        "за", "по", "из", "яйцеслав", "яйцеславыч", "бот", "ассистент",
    }
)


def _normalize(text: str) -> str:
    cleaned = _URL_RE.sub(" ", text or "")
    cleaned = _EMAIL_RE.sub(" ", cleaned)
    cleaned = _MENTION_RE.sub(" ", cleaned)
    cleaned = _COMMAND_RE.sub(" ", cleaned)
    return cleaned.lower().replace("ё", "е")


def extract_candidate_terms(text: str) -> tuple[str, ...]:
    """Извлекает кандидаты в локальный словарь, не сохраняя исходное сообщение."""

    normalized = _normalize(text)
    raw_tokens = _TOKEN_RE.findall(normalized)
    if not raw_tokens:
        return ()

    tokens = [token.strip("-'’") for token in raw_tokens]
    tokens = [token for token in tokens if token]

    candidates: set[str] = set()

    for token in tokens:
        if token in _STOPWORDS:
            continue
        if len(token) < 4:
            continue
        if token.isdigit():
            continue
        candidates.add(token)

    for left, right in zip(tokens, tokens[1:]):
        if left in _STOPWORDS and right in _STOPWORDS:
            continue
        if len(left) < 3 or len(right) < 3:
            continue
        phrase = f"{left} {right}"
        if len(phrase) <= 40:
            candidates.add(phrase)

    return tuple(sorted(candidates))


def compile_profile_terms(
    stats: Iterable[tuple[str, int, int]],
    *,
    limit: int = MAX_PROFILE_TERMS,
) -> tuple[str, ...]:
    """Выбирает устойчивые локальные слова/фразы по частоте и числу разных людей."""

    ranked: list[tuple[float, str]] = []

    for term, occurrences, distinct_users in stats:
        occurrences = int(occurrences)
        distinct_users = int(distinct_users)
        if occurrences < 3 or distinct_users < 2:
            continue
        phrase_bonus = 1.22 if " " in term else 1.0
        diversity_bonus = 1.0 + 0.42 * min(distinct_users, 5)
        score = occurrences * diversity_bonus * phrase_bonus * (1.0 + math.log1p(occurrences) * 0.08)
        ranked.append((score, term))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    return tuple(term for _, term in ranked[:limit])


def profile_is_ready(terms: Iterable[str], distinct_user_count: int) -> bool:
    return (
        distinct_user_count >= INITIAL_MIN_DISTINCT_USERS
        and len(tuple(terms)) >= INITIAL_MIN_SELECTED_TERMS
    )


def base_pack_weight(conversation_mode: str) -> float:
    return {
        "normal": 0.12,
        "greeting": 0.08,
        "challenge": 0.10,
        "hostile": 0.08,
    }.get(conversation_mode, 0.10)


def build_pack_instruction(
    terms: Iterable[str],
    *,
    conversation_mode: str,
    roughness: str,
) -> str:
    terms = tuple(terms)
    if not terms:
        return ""

    examples = ", ".join(repr(term) for term in terms[:18])
    lines = [
        "",
        "Речевой пакет этого ответа: chat_native.",
        "ЖЁСТКОЕ ПРАВИЛО V2: это отдельный 13-й пакет конкретного чата. Не смешивай его с classic/youth/skoof/blat/operative/battle/post-irony и другими пакетами.",
        "Это реальные устойчивые словечки и короткие фразы этого чата, собранные по частоте без хранения полного архива сообщений.",
        "Локальный материал: " + examples + ".",
        "Используй максимум один-два локальных элемента и только если они естественно подходят по смыслу. Не выдумывай историю происхождения мемов и не приписывай их конкретному человеку.",
        "Не копируй чужую реплику целиком. Говори своим предложением, но в местном ритме.",
    ]

    if conversation_mode in {"hostile", "challenge"}:
        lines.append(
            "Конфликтный тон разрешён по общим правилам Яйцеслава, но не превращай локальный сленг в обязательный taunt. Иногда достаточно коротко огрызнуться."
        )
    elif roughness == "high":
        lines.append("Мат и грубость допустимы по общим настройкам, но не обязаны присутствовать.")

    return "\n".join(lines)
