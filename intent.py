# ============================================================
# КЛАССИФИКАЦИЯ НАМЕРЕНИЯ И ЭМОЦИОНАЛЬНОГО ТОНА
#
# Локальная эвристика (regex + порядок приоритетов), без вызова
# Gemini на каждое сообщение — модель одна и на Free Tier, поэтому
# классификация не должна удваивать число запросов к API.
# Низкая уверенность — сигнал вызывающему коду выбрать нейтральный
# режим, а не гадать.
# ============================================================

import re

import personality

HIGH = "high"
MEDIUM = "medium"
LOW = "low"

INTENTS = frozenset(
    {
        "question",
        "request",
        "greeting",
        "agreement",
        "disagreement",
        "correction",
        "provocation",
        "joke",
        "sarcasm",
        "complaint",
        "emotional_support",
        "technical_help",
        "recommendation",
        "factual_lookup",
        "continuation",
        "clarification",
        "praise",
        "insult_directed_at_bot",
        "insult_about_third_party",
        "group_banter",
        "serious_issue",
        "unknown",
    }
)

EMOTIONAL_TONES = frozenset(
    {
        "neutral",
        "happy",
        "excited",
        "confused",
        "annoyed",
        "angry",
        "sad",
        "anxious",
        "grieving",
        "joking",
    }
)

# Тона, при которых нужно убрать грубость, случайные реакции
# и не начинать шутить — см. Этап 4 исходного плана.
HUMOR_SUPPRESSING_TONES = frozenset(
    {
        "sad",
        "anxious",
        "grieving",
    }
)


AGREEMENT_RE = re.compile(
    r"^\s*(?:да|ага|угу|согласен|согласна|точно|верно|именно|плюсую)\b",
    re.IGNORECASE,
)

DISAGREEMENT_RE = re.compile(
    r"^\s*(?:нет|не\s+согласен|не\s+согласна|неверно)\b|"
    r"\b(?:это\s+не\s+так|чушь|бред полный)\b",
    re.IGNORECASE,
)

CORRECTION_RE = re.compile(
    r"\b(?:на самом деле|вообще-то|ты\s+не\s+прав|ты\s+ошиб\w+|"
    r"это\s+неправильно|исправь\w*|неверно\s+говоришь)\b",
    re.IGNORECASE,
)

PROVOCATION_RE = re.compile(
    r"\b(?:слабо|докажи|спорим|бьюсь\s+об\s+заклад|сможешь\s+ли|"
    r"а\s+тебе\s+слабо)\b",
    re.IGNORECASE,
)

JOKE_MARKERS_RE = re.compile(
    r"(?:ахах|хах{2,}|лол|кек|😂|🤣|\)\){2,}|это\s+шутка)",
    re.IGNORECASE,
)

PRAISE_RE = re.compile(
    r"\b(?:молодец|классно|круто\s+ты|отлично\s+сделал|"
    r"хорошая\s+работа|умно\s+подмечено|хороший\s+вопрос)\b",
    re.IGNORECASE,
)

COMPLAINT_RE = re.compile(
    r"\b(?:достало|бесит|надоело|задолбал\w*|устал\w*\s+от|"
    r"раздражает)\b",
    re.IGNORECASE,
)

CLARIFICATION_RE = re.compile(
    r"\b(?:что\s+ты\s+имел\s+в\s+виду|поясни|уточни|не\s+понял\w*|"
    r"непонятно|что\s+значит\s+это)\b",
    re.IGNORECASE,
)

TECHNICAL_HELP_RE = re.compile(
    r"\b(?:как\s+(?:сделать|настроить|исправить|запустить|установить)|"
    r"почему\s+не\s+работает|ошибка\s+в|не\s+получается|баг\b|"
    r"как\s+мне\b)",
    re.IGNORECASE,
)

RECOMMENDATION_RE = re.compile(
    r"\b(?:посоветуй\w*|что\s+выбрать|что\s+лучше|стоит\s+ли|"
    r"порекомендуй\w*|какой\s+.*\s+выбрать)\b",
    re.IGNORECASE,
)

FACTUAL_LOOKUP_RE = re.compile(
    r"^\s*(?:что\s+такое|кто\s+такой|кто\s+такая|когда\s+было|"
    r"когда\s+произошл\w*|сколько\s+(?:будет|стоит|лет))\b",
    re.IGNORECASE,
)

QUESTION_WORD_RE = re.compile(
    r"^\s*(?:как|что|почему|зачем|когда|где|куда|кто|сколько|"
    r"можно\s+ли|а\s+если)\b",
    re.IGNORECASE,
)

REQUEST_RE = re.compile(
    r"^\s*(?:сделай|напиши|объясни|покажи|помоги|переведи|составь|"
    r"найди|расскажи|сгенерируй|придумай)\b",
    re.IGNORECASE,
)

# Слова-оскорбления шире, чем в personality.HOSTILE_RE — там нужна
# высокая точность направленности на бота, здесь достаточно просто
# опознать наличие оскорбления в тексте.
INSULT_WORD_RE = re.compile(
    r"\b(?:мудак\w*|дебил\w*|идиот\w*|кретин\w*|придурок\w*|"
    r"чмо|тупиц\w*|урод\w*)\b",
    re.IGNORECASE,
)

# Если рядом с оскорблением есть указание на человека — это третья
# сторона, а не предмет/явление ("этот код мудацкий" не в счёт).
PERSON_REFERENCE_RE = re.compile(
    r"\b(?:начальник\w*|друг\w*|брат\w*|сестр\w*|коллег\w*|"
    r"сосед\w*|муж|жена|парень|девушка|мама|папа|родител\w*|"
    r"он|она|они|человек\w*|препод\w*|училк\w*|учитель\w*)\b",
    re.IGNORECASE,
)

GRIEVING_RE = re.compile(
    r"\b(?:умер\w*|умира\w*|похорон\w*|скончал\w*)\b",
    re.IGNORECASE,
)

ANXIOUS_RE = re.compile(
    r"\b(?:суицид\w*|не\s+хочу\s+жить|покончить\s+с\s+собой|"
    r"паническ\w*|тревог\w*|боюсь\s+что)\b",
    re.IGNORECASE,
)

SAD_RE = re.compile(
    r"\b(?:грустно|плохо\s+на\s+душе|тяжело\s+на\s+душе|"
    r"депресс\w*|подавлен\w*|расстроен\w*|одиноко)\b",
    re.IGNORECASE,
)

ANGRY_RE = re.compile(
    r"\b(?:ненавижу|взбешен\w*|взбешён\w*|в\s+бешенстве)\b",
    re.IGNORECASE,
)

ANNOYED_RE = re.compile(
    r"\b(?:надоело|достало|бесит|раздражает)\b",
    re.IGNORECASE,
)

CONFUSED_RE = re.compile(
    r"\b(?:не\s+понимаю|запутал\w*|что\s+происходит|"
    r"ничего\s+не\s+понятно)\b",
    re.IGNORECASE,
)

EXCITED_RE = re.compile(
    r"(?:!{2,})|(?:\bвау\b)|(?:офигенно)|(?:огонь\s*!)",
    re.IGNORECASE,
)

HAPPY_RE = re.compile(
    r"\b(?:ура|рад\w*|класс\b|отлично|супер)\b|[😊🎉😄]",
    re.IGNORECASE,
)


def _has_person_directed_insult(
    lowered_text: str,
) -> bool:
    """Оскорбление рядом со словом, указывающим на человека."""

    for match in INSULT_WORD_RE.finditer(lowered_text):
        start = max(0, match.start() - 25)
        end = min(len(lowered_text), match.end() + 25)
        window = lowered_text[start:end]

        if PERSON_REFERENCE_RE.search(window):
            return True

    return False


def classify_intent(
    text: str,
    *,
    chat_type: str | None = None,
    recent_messages: list[str] | None = None,
) -> tuple[str, str]:
    """
    Определяет намерение сообщения и уверенность в результате.

    Возвращает (intent, confidence). При низкой уверенности
    вызывающий код должен выбирать нейтральный режим, а не
    достраивать поведение по слабому сигналу.
    """

    if not text or not text.strip():
        return "unknown", LOW

    lowered = text.lower().strip()

    if personality.is_serious_text(lowered):
        return "serious_issue", HIGH

    if TECHNICAL_HELP_RE.search(lowered):
        return "technical_help", HIGH

    if RECOMMENDATION_RE.search(lowered):
        return "recommendation", HIGH

    if FACTUAL_LOOKUP_RE.search(lowered):
        return "factual_lookup", HIGH

    if personality.GREETING_RE.search(lowered):
        return "greeting", HIGH

    if CORRECTION_RE.search(lowered):
        return "correction", MEDIUM

    if AGREEMENT_RE.search(lowered):
        return "agreement", MEDIUM

    if DISAGREEMENT_RE.search(lowered):
        return "disagreement", MEDIUM

    if PROVOCATION_RE.search(lowered):
        return "provocation", MEDIUM

    if personality.HOSTILE_RE.search(lowered):
        return "insult_directed_at_bot", HIGH

    if _has_person_directed_insult(lowered):
        return "insult_about_third_party", MEDIUM

    if COMPLAINT_RE.search(lowered):
        return "complaint", MEDIUM

    if CLARIFICATION_RE.search(lowered):
        return "clarification", MEDIUM

    if PRAISE_RE.search(lowered):
        return "praise", MEDIUM

    if JOKE_MARKERS_RE.search(lowered):
        return "joke", MEDIUM

    if QUESTION_WORD_RE.search(lowered) or lowered.endswith("?"):
        return "question", MEDIUM

    if REQUEST_RE.search(lowered):
        return "request", MEDIUM

    word_count = len(lowered.split())

    if (
        recent_messages
        and word_count <= 4
    ):
        return "continuation", LOW

    if chat_type in ("group", "supergroup"):
        return "group_banter", LOW

    return "unknown", LOW


def detect_emotional_tone(
    text: str,
) -> str:
    """Определяет эмоциональный тон сообщения одной меткой."""

    if not text or not text.strip():
        return "neutral"

    lowered = text.lower().strip()

    if GRIEVING_RE.search(lowered):
        return "grieving"

    if ANXIOUS_RE.search(lowered):
        return "anxious"

    if SAD_RE.search(lowered):
        return "sad"

    if ANGRY_RE.search(lowered):
        return "angry"

    if ANNOYED_RE.search(lowered):
        return "annoyed"

    if CONFUSED_RE.search(lowered):
        return "confused"

    if JOKE_MARKERS_RE.search(lowered):
        return "joking"

    if EXCITED_RE.search(lowered):
        return "excited"

    if HAPPY_RE.search(lowered):
        return "happy"

    return "neutral"


def humor_allowed_for_tone(
    tone: str,
) -> bool:
    """Проверяет, можно ли шутить при данном эмоциональном тоне."""

    return tone not in HUMOR_SUPPRESSING_TONES
