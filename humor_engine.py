# ============================================================
# HUMOR ENGINE
#
# Единый движок юмора: обычные шутки/подколы/сравнения и
# встречный стёб (banter_hostile) на прямую грубость в адрес
# бота — в одном модуле, чтобы не дублировать контроль повторов
# и проверку чувствительности темы в двух местах.
# ============================================================

import random
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import personality
import vocabulary
from intent import humor_allowed_for_tone

HUMOR_TYPES = (
    "light_taunt",
    "irony",
    "self_irony",
    "absurd",
    "unexpected_comparison",
    "callback",
    "hyperbole",
    "dry_comment",
    "pseudo_wisdom",
    "old_russian_metaphor",
    "gaming_terminology",
    "slang_2010s",
    "slang_2020s",
    "deadpan_official",
    "mundane_comparison",
    "grumbling",
    "praise_with_edge",
    "anti_joke",
    "comic_refusal",
    "observation",
)

BANTER_LEVEL_NONE = 0
BANTER_LEVEL_LIGHT = 1
BANTER_LEVEL_ROUGH = 2
BANTER_LEVEL_HARD = 3

BANTER_STRATEGIES_BY_LEVEL = {
    BANTER_LEVEL_LIGHT: (
        "mirror",
        "literal_reading",
        "self_irony",
    ),
    BANTER_LEVEL_ROUGH: (
        "mirror",
        "insult_flip",
        "deadpan_protocol",
        "technical_analogy",
        "calm_hyperbole",
    ),
    BANTER_LEVEL_HARD: (
        "insult_flip",
        "old_russian_verdict",
        "gaming_analogy",
        "short_absurd",
        "calm_hyperbole",
    ),
}

OUTCOME_BOT_WON = "bot_won"
OUTCOME_USER_WON = "user_won"
OUTCOME_DRAW = "draw"
OUTCOME_NO_CONTEST = "no_contest"

# Иногда признавать победу пользователя, чтобы персонаж выглядел
# живым, а не истеричным нарциссом, который никогда не проигрывает.
BANTER_USER_WIN_CHANCE = 0.15


@dataclass
class HumorContext:
    conversation_mode: str
    user_text: str = ""
    recent_messages: list[str] = field(default_factory=list)
    user_name: str = ""
    chat_type: str = "private"
    selected_character: str = "classic"
    roughness: str = "medium"
    response_style: str = "bold"
    serious_topic: bool = False
    bot_was_mentioned: bool = False
    relationship_level: int = 0
    message_intent: str = "unknown"
    intent_confidence: str = "low"
    emotional_tone: str = "neutral"


@dataclass
class HumorDecision:
    humor_allowed: bool
    humor_type: str | None = None
    intensity: int = 0
    selected_phrase: str | None = None
    selected_address: str | None = None
    selected_comparison: str | None = None
    callback_reference: str | None = None
    should_use_slang: bool = False
    should_use_old_russian: bool = False
    should_be_self_ironic: bool = False
    comeback_strategy: str | None = None
    outcome: str | None = None


# ============================================================
# КОНТРОЛЬ ПОВТОРОВ
# ============================================================

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "]+"
)


def normalize_phrase(
    text: str,
    *,
    strip_name: str = "",
) -> str:
    """Нормализует фразу для сравнения на почти-дубликаты."""

    normalized = text.lower().replace("ё", "е")

    if strip_name:
        normalized = normalized.replace(
            strip_name.lower(), ""
        )

    normalized = _EMOJI_RE.sub("", normalized)
    normalized = _PUNCT_RE.sub("", normalized)
    normalized = _SPACE_RE.sub(" ", normalized).strip()

    return normalized


def is_too_similar(
    candidate_norm: str,
    past_norm: str,
    threshold: float = 0.78,
) -> bool:
    """Сравнивает нормализованные фразы целиком и по первым 60 символам."""

    if not candidate_norm or not past_norm:
        return False

    full_ratio = SequenceMatcher(
        None, candidate_norm, past_norm
    ).ratio()

    if full_ratio >= threshold:
        return True

    prefix_ratio = SequenceMatcher(
        None,
        candidate_norm[:60],
        past_norm[:60],
    ).ratio()

    return prefix_ratio >= threshold


class RepetitionTracker:
    """
    Хранит недавно использованные фразы по чатам и по пулам,
    чтобы не повторять их слишком скоро.

    Каждый пул ограничен deque(maxlen=...) — рост внутри чата не
    бесконечный. Внешний словарь по chat_id чистится через
    prune_inactive(), иначе он рос бы вечно на долгоживущем процессе.
    """

    def __init__(self, maxlen: int = 20):
        self.maxlen = maxlen
        self._history: dict[int, dict[str, deque]] = defaultdict(dict)
        self._last_touched: dict[int, float] = {}

    def _pool(
        self,
        chat_id: int,
        pool_name: str,
    ) -> deque:
        chat_pools = self._history[chat_id]

        if pool_name not in chat_pools:
            chat_pools[pool_name] = deque(maxlen=self.maxlen)

        return chat_pools[pool_name]

    def record(
        self,
        chat_id: int,
        pool_name: str,
        phrase: str,
    ) -> None:
        self._last_touched[chat_id] = time.monotonic()
        self._pool(chat_id, pool_name).append(
            normalize_phrase(phrase)
        )

    def pick(
        self,
        chat_id: int,
        pool_name: str,
        candidates: list[str],
        threshold: float = 0.78,
    ) -> str | None:
        """Выбирает вариант, которого недавно не было в этом пуле."""

        if not candidates:
            return None

        self._last_touched[chat_id] = time.monotonic()
        history = self._pool(chat_id, pool_name)

        shuffled = list(candidates)
        random.shuffle(shuffled)

        for candidate in shuffled:
            candidate_norm = normalize_phrase(candidate)

            if not any(
                is_too_similar(candidate_norm, past, threshold)
                for past in history
            ):
                self.record(chat_id, pool_name, candidate)
                return candidate

        # Всё недавно использовано — чистим только этот пул,
        # а не всю историю чата.
        history.clear()
        chosen = random.choice(shuffled)
        self.record(chat_id, pool_name, chosen)
        return chosen

    def prune_inactive(
        self,
        max_age_seconds: float,
    ) -> list[int]:
        """Удаляет чаты, не тронутые дольше max_age_seconds. Возвращает их id."""

        now = time.monotonic()
        stale = [
            chat_id
            for chat_id, last_seen in self._last_touched.items()
            if now - last_seen > max_age_seconds
        ]

        for chat_id in stale:
            self._history.pop(chat_id, None)
            self._last_touched.pop(chat_id, None)

        return stale


REPETITION_TRACKER = RepetitionTracker(maxlen=20)
LAST_HUMOR_TYPE: dict[int, str] = {}


def prune_stale_state(
    max_age_seconds: float = 6 * 3600,
) -> int:
    """Чистит и трекер повторов, и память о последнем типе юмора."""

    stale_chat_ids = REPETITION_TRACKER.prune_inactive(max_age_seconds)

    for chat_id in stale_chat_ids:
        LAST_HUMOR_TYPE.pop(chat_id, None)

    return len(stale_chat_ids)


# ============================================================
# ОБЫЧНЫЙ ЮМОР (не встречный стёб)
# ============================================================

_TYPE_CHANCE_BY_MODE = {
    "normal": 0.35,
    "greeting": 0.30,
    "challenge": 0.55,
    "hostile": 0.0,
    "serious": 0.0,
}

_CHARACTER_TYPE_FILTERS = {
    "professor": (
        "dry_comment",
        "pseudo_wisdom",
        "observation",
        "deadpan_official",
        "self_irony",
    ),
    "calm": tuple(
        t
        for t in HUMOR_TYPES
        if t not in ("anti_joke", "comic_refusal", "hyperbole")
    ),
}


def _eligible_humor_types(
    ctx: HumorContext,
) -> list[str]:
    allowed = _CHARACTER_TYPE_FILTERS.get(
        ctx.selected_character, HUMOR_TYPES
    )
    return list(allowed)


def _all_comparisons() -> list[str]:
    combined: list[str] = []

    for items in vocabulary.ABSURD_COMPARISONS.values():
        combined.extend(items)

    return combined


def _comparison_pool(
    humor_type: str,
) -> list[str]:
    if humor_type == "mundane_comparison":
        return list(
            vocabulary.ABSURD_COMPARISONS.get(
                "бытовые ситуации", []
            )
        )

    return _all_comparisons()


def decide_humor(
    ctx: HumorContext,
    chat_id: int,
    tracker: RepetitionTracker = REPETITION_TRACKER,
    *,
    remember_type: bool = True,
) -> HumorDecision:
    """
    Решает, нужна ли обычная шутка в этом ответе, и какая именно.

    Не используется для прямой грубости в адрес бота —
    для этого есть decide_banter().
    """

    if (
        ctx.serious_topic
        or ctx.message_intent in ("serious_issue", "emotional_support")
        or not humor_allowed_for_tone(ctx.emotional_tone)
        or ctx.response_style == "serious"
    ):
        return HumorDecision(humor_allowed=False)

    base_chance = _TYPE_CHANCE_BY_MODE.get(
        ctx.conversation_mode, 0.30
    )

    if ctx.chat_type in ("group", "supergroup"):
        # Групповой тон всегда острее личного и не зависит от того,
        # что у конкретного участника выставлена низкая грубость —
        # это осознанное решение, не баг.
        base_chance = max(base_chance, 0.45)
    elif ctx.roughness == "low":
        base_chance *= 0.5
    elif ctx.roughness == "high":
        base_chance = min(1.0, base_chance * 1.3)

    if ctx.bot_was_mentioned:
        base_chance = min(1.0, base_chance + 0.15)

    if random.random() >= base_chance:
        return HumorDecision(humor_allowed=False)

    candidates = _eligible_humor_types(ctx)
    last_type = (
        LAST_HUMOR_TYPE.get(chat_id)
        if remember_type
        else None
    )

    if last_type and last_type in candidates and len(candidates) > 1:
        candidates = [t for t in candidates if t != last_type]

    humor_type = random.choice(candidates)
    if remember_type:
        LAST_HUMOR_TYPE[chat_id] = humor_type

    decision = HumorDecision(
        humor_allowed=True,
        humor_type=humor_type,
        intensity=1,
    )

    if humor_type == "light_taunt":
        pool = vocabulary.TAUNTS_YOUTH + vocabulary.TAUNTS_SKOOF
        decision.selected_phrase = tracker.pick(chat_id, "taunt", pool)

    elif humor_type == "self_irony":
        decision.selected_phrase = tracker.pick(
            chat_id, "self_irony", vocabulary.SELF_IRONY
        )
        decision.should_be_self_ironic = True

    elif humor_type in (
        "absurd",
        "unexpected_comparison",
        "mundane_comparison",
    ):
        pool = _comparison_pool(humor_type)
        decision.selected_comparison = tracker.pick(
            chat_id, "comparison", pool
        )

    elif humor_type == "dry_comment":
        pool = (
            vocabulary.REACTION_LINES["observation"]
            + vocabulary.REACTION_LINES["soft_taunt"]
        )
        decision.selected_phrase = tracker.pick(chat_id, "reaction", pool)

    elif humor_type == "observation":
        decision.selected_phrase = tracker.pick(
            chat_id, "reaction", vocabulary.REACTION_LINES["observation"]
        )

    elif humor_type == "grumbling":
        decision.selected_phrase = tracker.pick(
            chat_id, "reaction", vocabulary.REACTION_LINES["disappointment"]
        )

    elif humor_type == "pseudo_wisdom":
        decision.selected_phrase = tracker.pick(
            chat_id, "wisdom", vocabulary.WISDOMS
        )

    elif humor_type == "praise_with_edge":
        decision.selected_phrase = tracker.pick(
            chat_id, "compliment", vocabulary.COMPLIMENTS_WITH_EDGE
        )

    elif humor_type == "old_russian_metaphor":
        decision.should_use_old_russian = True

    elif humor_type in ("slang_2010s", "slang_2020s"):
        decision.should_use_slang = True

    elif humor_type == "callback" and ctx.recent_messages:
        decision.callback_reference = ctx.recent_messages[-1]

    return decision


# ============================================================
# ВСТРЕЧНЫЙ СТЁБ (banter_hostile)
# ============================================================


def detect_directed_insult(
    text: str,
    mode: str | None = None,
) -> bool:
    """Проверяет, что грубость направлена именно на бота, а не на третье лицо."""

    if mode is None:
        mode = personality.detect_conversation_mode(text)

    return mode == "hostile"


def estimate_banter_intensity(
    ctx: HumorContext,
) -> int:
    """
    Оценивает допустимую жёсткость встречного стёба.

    Уровень 3 допустим только в несерьёзной теме и когда
    грубость пользователя/группы это разрешает.
    """

    if (
        ctx.serious_topic
        or not humor_allowed_for_tone(ctx.emotional_tone)
    ):
        return BANTER_LEVEL_NONE

    intensity = BANTER_LEVEL_ROUGH

    if ctx.chat_type in ("group", "supergroup"):
        intensity = BANTER_LEVEL_HARD
    elif ctx.roughness == "low":
        intensity = BANTER_LEVEL_LIGHT
    elif ctx.roughness == "high":
        intensity = BANTER_LEVEL_HARD

    if ctx.response_style == "serious":
        intensity = min(intensity, BANTER_LEVEL_LIGHT)

    return intensity


def build_comeback_context(
    ctx: HumorContext,
    chat_id: int,
) -> dict:
    """Собирает минимум данных, нужный для выбора стратегии ответа."""

    return {
        "chat_id": chat_id,
        "user_name": ctx.user_name,
        "relationship_level": ctx.relationship_level,
        "recent_messages": list(ctx.recent_messages[-5:]),
    }


def select_comeback_strategy(
    intensity: int,
) -> str:
    """Выбирает стратегию встречного стёба под уровень интенсивности."""

    pool = BANTER_STRATEGIES_BY_LEVEL.get(
        intensity, BANTER_STRATEGIES_BY_LEVEL[BANTER_LEVEL_ROUGH]
    )
    return random.choice(pool)


def decide_banter(
    ctx: HumorContext,
    chat_id: int,
    tracker: RepetitionTracker = REPETITION_TRACKER,
) -> HumorDecision:
    """
    Решает встречный стёб на прямую грубость в адрес бота.

    Не читает мораль, не изображает обиду: либо короткий
    встречный подкол, либо (иногда) признание, что подкол
    пользователя удался.
    """

    if not detect_directed_insult(ctx.user_text, ctx.conversation_mode):
        return HumorDecision(humor_allowed=False)

    intensity = estimate_banter_intensity(ctx)

    if intensity == BANTER_LEVEL_NONE:
        return HumorDecision(humor_allowed=False)

    pool = vocabulary.BANTER_COMEBACKS_BY_LEVEL.get(
        intensity, vocabulary.BANTER_COMEBACKS_LEVEL_2
    )
    phrase = tracker.pick(chat_id, "banter", pool)
    strategy = select_comeback_strategy(intensity)

    outcome = OUTCOME_BOT_WON

    if random.random() < BANTER_USER_WIN_CHANCE:
        outcome = random.choice((OUTCOME_USER_WON, OUTCOME_DRAW))
        phrase = tracker.pick(
            chat_id, "self_irony", vocabulary.SELF_IRONY
        )

    return HumorDecision(
        humor_allowed=True,
        humor_type="banter_hostile",
        intensity=intensity,
        selected_phrase=phrase,
        comeback_strategy=strategy,
        outcome=outcome,
    )
