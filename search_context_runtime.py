"""Context recovery and proof-safe handling for explicit web-search follow-ups.

Besides bare ``проверь в интернете`` follow-ups, this layer treats relative-time
phrases such as ``вчера``, ``сегодня`` and ``только что`` as freshness signals.
Weak/anaphoric queries are combined with the previous chat topic so a request
like ``он вчера прилетел, проверь`` does not lose the entity and accidentally
surface an old but lexically similar story.

It also catches natural in-sentence search requests (including common chat typos)
and proof challenges such as ``а ссылки где?``. A normal Gemini answer is never
allowed to pretend it browsed the web: only a prompt that actually contains
search results may claim that. Text-mode real-search answers get deterministic
source URLs appended if the model forgets them. None of this adds an extra web
or Gemini call.
"""

from __future__ import annotations

import functools
import logging
import re
import sys
from typing import Any


_INSTALLED = False
_CURRENT_DATE_QUERY_RE = re.compile(
    r"(?:"
    r"\b(?:какой|который)\s+(?:сейчас\s+)?год\b|"
    r"\bгод\s+(?:сейчас\s+)?(?:какой|который)\b|"
    r"\b(?:какая|которая)\s+(?:сейчас\s+)?дата\b|"
    r"\bдата\s+(?:сейчас\s+)?(?:какая|которая)\b|"
    r"\bкакое\s+сегодня\s+число\b|"
    r"\bсегодняшн\w*\s+дата\b|"
    r"\bwhat\s+(?:year|date)\s+is\s+it\b|"
    r"\bwhat(?:'s|\s+is)\s+the\s+date\b"
    r")",
    re.IGNORECASE,
)

_FRESHNESS_RE = re.compile(
    r"(?:"
    r"\bсегодня\b|\bвчера\b|\bпозавчера\b|\bсейчас\b|"
    r"\bтолько\s+что\b|\bнедавно\b|\bсвеж\w*\b|\bактуальн\w*\b|"
    r"\bпоследн\w*\s+(?:новост\w*|событ\w*|данн\w*)\b|"
    r"\bза\s+(?:сегодня|вчера|последн\w*\s+(?:час|день|сутк|недел)\w*)\b|"
    r"\b(?:today|yesterday|just\s+now|latest|recent)\b"
    r")",
    re.IGNORECASE,
)

_WEAK_FOLLOWUP_RE = re.compile(
    r"(?:"
    r"^\s*(?:не\s+)?(?:вот\s+)?(?:он|она|они|это|там|так)\b|"
    r"\b(?:он|она|они|это)\s+(?:же\s+)?(?:вчера|сегодня|недавно|только\s+что)\b|"
    r"\b(?:я\s+же\s+говорю|вот\s+же|прям\s+вчера)\b"
    r")",
    re.IGNORECASE,
)

# Deliberately requires an explicit web/location word (or a dedicated web verb)
# so ordinary phrases such as ``ты не проверяешь факты`` remain accountability
# signals rather than silently spending a search request.
_NATURAL_WEB_REQUEST_RE = re.compile(
    r"(?:"
    r"\b(?:проверь|проверить|посмотри|глянь|поищи|найди|чекни)\b"
    r".{0,28}?\b(?:в|во|а)?\s*(?:интернет(?:е|у)?|инете|сети|онлайн)\b|"
    r"\b(?:погугли|загугли|гугли)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_NEWS_VERIFY_RE = re.compile(
    r"(?:"
    r"\b(?:проверь|проверил|проверял|проверишь)\b.{0,28}\bновост\w*\b|"
    r"\bновост\w*\b.{0,28}\b(?:проверь|проверил|проверял|проверишь)\b|"
    r"\bпо\s+фактам\b.{0,35}\bновост\w*\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_PROOF_REQUEST_RE = re.compile(
    r"(?:"
    r"\b(?:а\s+)?(?:ссылк\w*|источник\w*)\s+(?:где|есть)\b|"
    r"\b(?:где|покажи|дай|скинь)\s+(?:ссылк\w*|источник\w*)\b|"
    r"\bоткуда\s+(?:инфа|информация|данные|новости)\b|"
    r"\bсам\s+(?:это\s+)?(?:придумал|выдумал)\b.{0,24}\b(?:новост\w*|факт\w*|данн\w*)\b|"
    r"\b(?:новост\w*|факт\w*|данн\w*)\b.{0,24}\b(?:придумал|выдумал)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_FILLER_ONLY_RE = re.compile(
    r"^(?:(?:ну|а|и|так|вот|ты|давай|пожалуйста|плиз|короче|тогда)\s*)+$",
    re.IGNORECASE,
)

_URL_RE = re.compile(r"https?://[^\s<>\]\[)]+", re.IGNORECASE)
_SEARCH_RESULTS_MARKER = "Результаты поиска:"
_TEXT_SOURCE_RULE_MARKER = "в конце добавь раздел «Источники»"

_WEB_GROUNDING_INSTRUCTION = """

ПРАВИЛО ПРО ИНТЕРНЕТ И АКТУАЛЬНЫЕ ДАННЫЕ:
Не утверждай, что ты «проверил в интернете», «глянул в сети», «прошёлся по
каналам», увидел текущие котировки/новости или нашёл источники, если В ТЕКУЩЕМ
запросе модели нет явно переданного блока «Результаты поиска:» с реальными
результатами веб-поиска. История чата и память не являются доказательством нового
поиска. Без такого блока не выдумывай свежие цены, ставки, новости и источники.
Если пользователь просит именно свежую проверку, а реального search-контекста в
этом запросе нет, не изображай браузинг и не защищай неподтверждённые факты.
"""


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "perform_web_search", None)):
            return module
    return None


def _is_current_date_query(query: str) -> bool:
    return bool(_CURRENT_DATE_QUERY_RE.search(query or ""))


def is_freshness_query(query: str) -> bool:
    return bool(_FRESHNESS_RE.search(str(query or "")))


def _looks_weak_followup(query: str) -> bool:
    text = " ".join(str(query or "").split()).strip()
    if not text:
        return True
    if _WEAK_FOLLOWUP_RE.search(text):
        return True
    # Very short fresh requests often contain only a pronoun/action/time marker.
    return is_freshness_query(text) and len(text.split()) <= 7


def _clean_candidate(text: str) -> str:
    return re.sub(r"^[\s,.:;!?—-]+|[\s,.:;!?—-]+$", "", str(text or "")).strip()


def extract_natural_search_query(text: str) -> str | None:
    """Return a concrete query, ``""`` for prior-topic reuse, or ``None``.

    This supplements bot.py's prefix-only SEARCH_TRIGGER_RE. Empty-string is a
    meaningful result: ``perform_web_search`` already knows how to recover the
    previous group/private topic for a bare follow-up.
    """

    value = " ".join(str(text or "").split()).strip()
    if not value:
        return None

    # Proof/source challenges refer to the immediately preceding factual topic.
    if _PROOF_REQUEST_RE.search(value) or _NEWS_VERIFY_RE.search(value):
        return ""

    match = _NATURAL_WEB_REQUEST_RE.search(value)
    if not match:
        return None

    after = _clean_candidate(value[match.end():])
    if after:
        return after

    before = _clean_candidate(value[:match.start()])
    if before and not _FILLER_ONLY_RE.fullmatch(before):
        return before
    return ""


def _previous_search_topic(module: Any, update: Any, context: Any) -> str:
    chat = getattr(update, "effective_chat", None)
    if chat is None:
        return ""

    if str(getattr(chat, "type", "")) == "private":
        try:
            previous = str(context.user_data.get("last_user_query", "")).strip()
        except Exception:
            previous = ""
        if previous:
            return previous

    memory_store = getattr(module, "GROUP_MEMORY", {})
    memory = memory_store.get(getattr(chat, "id", None)) if memory_store else None
    if not memory:
        return ""

    extract_search_query = getattr(module, "extract_search_query", None)
    for entry in reversed(memory):
        try:
            _timestamp, role, _author, text = entry
        except (TypeError, ValueError):
            continue
        if role != "user":
            continue
        candidate = str(text or "").strip()
        if not candidate:
            continue
        if callable(extract_search_query):
            extracted = extract_search_query(candidate)
            if extracted is not None:
                extracted = str(extracted).strip()
                if extracted:
                    return extracted
                continue
        return candidate
    return ""


def _combine_with_previous_topic(module: Any, update: Any, context: Any, query: str) -> str:
    current = " ".join(str(query or "").split()).strip()
    if not current or not _looks_weak_followup(current):
        return current

    previous = _previous_search_topic(module, update, context)
    if not previous:
        return current
    if previous.lower() in current.lower() or current.lower() in previous.lower():
        return current

    combined = f"{previous}. Уточнение пользователя: {current}"
    logging.info("Fresh/anaphoric search reused previous topic: %r", combined[:220])
    return combined


def _install_natural_search_extractor(module: Any) -> None:
    original = getattr(module, "extract_search_query", None)
    if not callable(original) or getattr(original, "_yayceslav_natural_web", False):
        return

    @functools.wraps(original)
    def extract_search_query_natural(text: str) -> str | None:
        existing = original(text)
        if existing is not None:
            return existing
        return extract_natural_search_query(text)

    extract_search_query_natural._yayceslav_natural_web = True
    module.extract_search_query = extract_search_query_natural


def _install_no_fake_browsing_instruction(module: Any) -> None:
    original = getattr(module, "build_full_system_instruction", None)
    if not callable(original) or getattr(original, "_yayceslav_web_grounding", False):
        return

    @functools.wraps(original)
    def build_with_web_grounding(*args, **kwargs):
        return str(original(*args, **kwargs)) + _WEB_GROUNDING_INSTRUCTION

    build_with_web_grounding._yayceslav_web_grounding = True
    module.build_full_system_instruction = build_with_web_grounding


def _unique_prompt_urls(prompt: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for raw in _URL_RE.findall(prompt or ""):
        url = raw.rstrip(".,;:!?")
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= 5:
            break
    return urls


def _install_search_source_proof(module: Any) -> None:
    """Guarantee visible proof on real text searches without another API call."""

    original = getattr(module, "ask_gemini", None)
    if not callable(original) or getattr(original, "_yayceslav_search_source_proof", False):
        return

    @functools.wraps(original)
    async def ask_gemini_with_search_proof(contents: Any, *args, **kwargs):
        answer = await original(contents, *args, **kwargs)
        prompt = contents if isinstance(contents, str) else ""
        if (
            _SEARCH_RESULTS_MARKER not in prompt
            or _TEXT_SOURCE_RULE_MARKER not in prompt
        ):
            return answer

        urls = _unique_prompt_urls(prompt)
        if len(urls) < 2:
            return answer

        answer_text = str(answer or "").strip()
        present = {url for url in urls if url in answer_text}
        missing = [url for url in urls if url not in present]
        if len(present) >= 2:
            return answer

        needed = max(0, 2 - len(present))
        selected = missing[:needed]
        if not selected:
            return answer

        suffix = "\n".join(f"- {url}" for url in selected)
        if re.search(r"\n\s*(?:Источники|Sources)\s*:?", answer_text, re.IGNORECASE):
            return answer_text + "\n" + suffix
        return answer_text + "\n\nИсточники:\n" + suffix

    ask_gemini_with_search_proof._yayceslav_search_source_proof = True
    module.ask_gemini = ask_gemini_with_search_proof


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED

    module = bot_module or _find_bot_module()
    if module is None:
        return False

    _install_natural_search_extractor(module)
    _install_no_fake_browsing_instruction(module)
    _install_search_source_proof(module)

    # Extend the existing news/freshness gate without changing search cost or
    # adding another network call. search_web will keep using the same DDGS call,
    # but relative-date requests now receive the existing month timelimit.
    original_is_news_query = getattr(module, "is_news_query", None)
    if callable(original_is_news_query) and not getattr(original_is_news_query, "_yayceslav_freshness", False):
        def is_news_query_with_freshness(query: str) -> bool:
            return bool(original_is_news_query(query) or is_freshness_query(query))

        is_news_query_with_freshness._yayceslav_freshness = True
        module.is_news_query = is_news_query_with_freshness

    original = module.perform_web_search
    if getattr(original, "_yayceslav_search_context", False):
        _INSTALLED = True
        return True

    async def perform_web_search_with_context(
        update: Any,
        context: Any,
        query: str,
        force_voice: bool = False,
    ) -> None:
        resolved_query = str(query or "").strip()
        if not resolved_query:
            resolved_query = _previous_search_topic(module, update, context)
            if resolved_query:
                logging.info(
                    "Bare search/proof follow-up reused previous topic: %r",
                    resolved_query[:160],
                )
        else:
            resolved_query = _combine_with_previous_topic(
                module, update, context, resolved_query
            )

        if resolved_query and _is_current_date_query(resolved_query):
            if not await module.enforce_rate_limit(update, "search"):
                return
            now_msk = module.current_msk_datetime()
            await module.register_user_and_chat(update)
            await module.increment_stat("total_requests")
            await module.increment_stat("search_requests")
            message = getattr(update, "effective_message", None)
            if message is not None:
                await message.reply_text(
                    f"Сейчас {now_msk.year} год. "
                    f"Системная дата: {now_msk.strftime('%d.%m.%Y')} (МСК)."
                )
                await module.increment_stat("bot_answers")
            return

        await original(
            update=update,
            context=context,
            query=resolved_query,
            force_voice=force_voice,
        )

    perform_web_search_with_context._yayceslav_search_context = True
    module.perform_web_search = perform_web_search_with_context
    module._yayceslav_search_context_installed = True
    _INSTALLED = True
    logging.warning(
        "Search context runtime ready: natural/proof follow-ups + source proof + no fake browsing + relative-date freshness"
    )
    return True
