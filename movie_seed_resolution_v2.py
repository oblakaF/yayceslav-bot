"""Robust seed resolution for the TMDB recommendation vertical.

TMDB recommendation quality is irrelevant if the seed movie is wrong.  The
first implementation sent the captured Russian phrase almost literally to
``search/movie`` and then trusted result position.  Live group testing exposed
that ``в духе Дюны`` could therefore resolve to an unrelated same-ish title and
make the downstream genre/keyword recommender consistently recommend the wrong
kind of films.

This layer stays provider-only (no second Gemini call):
- searches a few conservative Russian title-form variants (Дюны -> Дюна,
  Матрицу -> Матрица);
- understands an explicit year;
- if a full query such as ``дюна вильнева`` is a poor title match, it retries a
  title prefix and treats the short tail as a possible director qualifier;
- resolves that qualifier through TMDB people and verifies candidate credits;
- rejects weak title matches instead of confidently seeding from unrelated data.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from difflib import SequenceMatcher
import math
import re
from typing import Any, Iterable

import movie_recommendation_runtime as movie_runtime


MIN_ACCEPTED_TITLE_SIMILARITY = 0.64
STRONG_TITLE_SIMILARITY = 0.80
MAX_SEARCH_VARIANTS = 4
MAX_CREDIT_CHECKS = 6

_YEAR_RE = re.compile(r"(?<!\d)(?P<year>(?:19|20)\d{2})(?!\d)")
_EXPLICIT_DIRECTOR_RE = re.compile(
    r"^(?P<title>.+?)\s+(?:(?:режисс[её]ра?|режиссер(?:а)?)\s+|от\s+)(?P<director>[^,;]+)$",
    re.IGNORECASE,
)
_CYRILLIC_WORD_RE = re.compile(r"^[а-яё-]+$", re.IGNORECASE)

_INSTALLED = False


@dataclass(frozen=True)
class SeedQuery:
    raw: str
    title: str
    year: int = 0
    director_hint: str = ""


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip(" \t\r\n,.:;!?—-\"'«»")


def _fold(value: Any) -> str:
    text = _clean(value).casefold().replace("ё", "е")
    text = re.sub(r"[^0-9a-zа-я]+", " ", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def parse_seed_query(query: str) -> SeedQuery:
    raw = movie_runtime._clean_query(query)
    if not raw:
        return SeedQuery(raw="", title="")

    year = 0
    year_match = _YEAR_RE.search(raw)
    if year_match:
        year = int(year_match.group("year"))
        raw_without_year = _clean(_YEAR_RE.sub(" ", raw))
    else:
        raw_without_year = raw

    director_hint = ""
    title = raw_without_year
    explicit = _EXPLICIT_DIRECTOR_RE.match(raw_without_year)
    if explicit:
        title = _clean(explicit.group("title"))
        director_hint = _clean(explicit.group("director"))

    return SeedQuery(raw=raw, title=title, year=year, director_hint=director_hint)


def _replace_last_word(text: str, replacement: str) -> str:
    words = text.split()
    if not words:
        return text
    words[-1] = replacement
    return " ".join(words)


def title_variants(title: str) -> tuple[str, ...]:
    """Return bounded search alternatives; original title always comes first."""

    clean = _clean(title)
    if not clean:
        return ()

    variants: list[str] = [clean]
    last = clean.split()[-1]
    folded_last = last.casefold()

    # Common Russian case forms seen after ``в духе``/``похож на``.
    # They are alternatives only: a legitimate indeclinable/title word is never
    # thrown away merely because one suffix happens to match.
    if _CYRILLIC_WORD_RE.match(last) and len(last) >= 4:
        if folded_last.endswith("ы"):
            variants.append(_replace_last_word(clean, last[:-1] + "а"))
        if folded_last.endswith("у") and not folded_last.endswith("ру"):
            variants.append(_replace_last_word(clean, last[:-1] + "а"))

    # TMDB Russian aliases sometimes use е where user typed ё or vice versa.
    if "ё" in clean.casefold():
        variants.append(re.sub("ё", "е", clean, flags=re.IGNORECASE))

    return tuple(dict.fromkeys(item for item in variants if item))[:MAX_SEARCH_VARIANTS]


def director_name_variants(name: str) -> tuple[str, ...]:
    """Conservatively undo a common Russian genitive surname ending."""

    clean = _clean(name)
    if not clean:
        return ()
    variants = [clean]
    words = clean.split()
    last = words[-1]
    if _CYRILLIC_WORD_RE.match(last) and len(last) >= 5 and last.casefold().endswith("а"):
        variants.append(_replace_last_word(clean, last[:-1]))
    if "ё" in clean.casefold():
        variants.append(re.sub("ё", "е", clean, flags=re.IGNORECASE))
    return tuple(dict.fromkeys(item for item in variants if item))[:3]


def _similarity(left: str, right: str) -> float:
    a = _fold(left)
    b = _fold(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def title_similarity(title_queries: Iterable[str], movie: dict[str, Any]) -> float:
    values = (
        str(movie.get("title") or ""),
        str(movie.get("original_title") or ""),
    )
    return max(
        (_similarity(query, value) for query in title_queries for value in values),
        default=0.0,
    )


async def _search_movies(title: str) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    variants = title_variants(title)
    if not variants:
        return [], ()

    payloads = await asyncio.gather(
        *[
            movie_runtime._tmdb_get(
                "search/movie",
                {
                    "query": variant,
                    "include_adult": "false",
                    "language": "ru-RU",
                },
            )
            for variant in variants
        ],
        return_exceptions=True,
    )

    by_id: dict[int, dict[str, Any]] = {}
    for variant_index, (variant, payload) in enumerate(zip(variants, payloads)):
        if isinstance(payload, BaseException):
            continue
        for rank, row in enumerate(movie_runtime._results(payload)[:10], start=1):
            movie = movie_runtime._movie_summary(row)
            if not movie:
                continue
            movie_id = int(movie["id"])
            existing = by_id.get(movie_id)
            search_rank = rank + variant_index * 2
            if existing is None:
                current = dict(movie)
                current["_seed_search_rank"] = search_rank
                current["_seed_search_variants"] = [variant]
                by_id[movie_id] = current
            else:
                existing["_seed_search_rank"] = min(
                    int(existing.get("_seed_search_rank") or search_rank), search_rank
                )
                seen = list(existing.get("_seed_search_variants") or [])
                if variant not in seen:
                    seen.append(variant)
                existing["_seed_search_variants"] = seen
    return list(by_id.values()), variants


def _best_similarity(rows: list[dict[str, Any]], variants: Iterable[str]) -> float:
    return max((title_similarity(variants, row) for row in rows), default=0.0)


async def _resolve_bare_director_tail(
    title: str,
) -> tuple[str, str, list[dict[str, Any]], tuple[str, ...]] | None:
    """Try ``<movie title> <director>`` only when the full title is weak."""

    words = title.split()
    if len(words) < 2:
        return None

    # One-word surname first, then a two-word full name (``дени вильнева``).
    for suffix_len in (1, 2):
        if len(words) <= suffix_len:
            continue
        prefix = _clean(" ".join(words[:-suffix_len]))
        suffix = _clean(" ".join(words[-suffix_len:]))
        rows, variants = await _search_movies(prefix)
        if rows and _best_similarity(rows, variants) >= STRONG_TITLE_SIMILARITY:
            return prefix, suffix, rows, variants
    return None


async def _resolve_director_person_ids(hint: str) -> set[int]:
    variants = director_name_variants(hint)
    if not variants:
        return set()
    payloads = await asyncio.gather(
        *[
            movie_runtime._tmdb_get(
                "search/person",
                {"query": variant, "include_adult": "false", "language": "ru-RU"},
            )
            for variant in variants
        ],
        return_exceptions=True,
    )
    ids: set[int] = set()
    for payload in payloads:
        if isinstance(payload, BaseException) or not isinstance(payload, dict):
            continue
        for row in payload.get("results") or []:
            if not isinstance(row, dict):
                continue
            try:
                person_id = int(row.get("id") or 0)
            except (TypeError, ValueError):
                continue
            department = str(row.get("known_for_department") or "").casefold()
            if person_id > 0 and (not department or department == "directing"):
                ids.add(person_id)
    return ids


def _director_ids_from_credits(payload: Any) -> set[int]:
    if not isinstance(payload, dict):
        return set()
    ids: set[int] = set()
    for row in payload.get("crew") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("job") or "").casefold() != "director":
            continue
        try:
            person_id = int(row.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if person_id > 0:
            ids.add(person_id)
    return ids


def _base_score(
    movie: dict[str, Any],
    *,
    variants: tuple[str, ...],
    requested_year: int,
) -> tuple[float, float]:
    similarity = title_similarity(variants, movie)
    rank = max(1, int(movie.get("_seed_search_rank") or 99))
    score = similarity * 180.0 + max(0.0, 32.0 - rank)
    if similarity >= 0.995:
        score += 45.0

    movie_year = int(movie.get("year") or 0)
    if requested_year:
        if movie_year == requested_year:
            score += 120.0
        elif movie_year:
            score -= min(70.0, 25.0 + abs(movie_year - requested_year) * 2.0)

    # Popularity is only a tie-breaker between plausible title matches.  It is
    # intentionally too weak to rescue an unrelated high-profile movie.
    vote_count = max(0, int(movie.get("vote_count") or 0))
    popularity = max(0.0, float(movie.get("popularity") or 0.0))
    score += min(math.log10(vote_count + 1), 5.0) * 5.0
    score += min(popularity, 100.0) * 0.04
    return score, similarity


async def resolve_seed_movie(query: str) -> dict[str, Any] | None:
    parsed = parse_seed_query(query)
    if not parsed.title:
        return None

    title = parsed.title
    director_hint = parsed.director_hint
    rows, variants = await _search_movies(title)

    # A weak full-title query may actually be ``title + director``.  Do not do
    # this split when TMDB already sees a strong title, because multi-word movie
    # titles must remain intact.
    if not director_hint and _best_similarity(rows, variants) < STRONG_TITLE_SIMILARITY:
        fallback = await _resolve_bare_director_tail(title)
        if fallback is not None:
            title, director_hint, rows, variants = fallback

    if not rows:
        return None

    ranked: list[tuple[float, float, dict[str, Any]]] = []
    for movie in rows:
        score, similarity = _base_score(
            movie,
            variants=variants,
            requested_year=parsed.year,
        )
        ranked.append((score, similarity, movie))

    # Only pay the extra people/credits requests when the user actually supplied
    # a director-like qualifier.  This keeps ordinary recommendations cheap.
    director_ids: set[int] = set()
    if director_hint:
        director_ids = await _resolve_director_person_ids(director_hint)
        if director_ids:
            prelim = sorted(ranked, key=lambda item: item[0], reverse=True)[:MAX_CREDIT_CHECKS]
            credit_payloads = await asyncio.gather(
                *[
                    movie_runtime._tmdb_get(f"movie/{int(item[2]['id'])}/credits")
                    for item in prelim
                ],
                return_exceptions=True,
            )
            director_match_by_id: dict[int, bool] = {}
            for (_, _, movie), payload in zip(prelim, credit_payloads):
                matched = False
                if not isinstance(payload, BaseException):
                    matched = bool(_director_ids_from_credits(payload) & director_ids)
                director_match_by_id[int(movie["id"])] = matched

            rescored: list[tuple[float, float, dict[str, Any]]] = []
            for score, similarity, movie in ranked:
                movie_id = int(movie["id"])
                if movie_id in director_match_by_id:
                    score += 220.0 if director_match_by_id[movie_id] else -75.0
                rescored.append((score, similarity, movie))
            ranked = rescored

    ranked.sort(key=lambda item: item[0], reverse=True)
    best_score, best_similarity, best = ranked[0]
    del best_score

    # The important fail-safe: no downstream recommendation run from a title
    # that TMDB itself did not match reasonably well.
    if best_similarity < MIN_ACCEPTED_TITLE_SIMILARITY:
        return None

    result = {
        key: value
        for key, value in best.items()
        if not str(key).startswith("_seed_")
    }
    if director_hint:
        result["seed_director_hint"] = director_hint
        result["seed_director_verified"] = bool(director_ids)
    return result


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    movie_runtime.resolve_seed_movie = resolve_seed_movie
    _INSTALLED = True
    return True


install()
