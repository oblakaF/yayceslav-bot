# Yayceslav Roadmap v2

This roadmap tracks the next architecture phase after the September 2026 personality/memory foundation was completed. The goal remains the same: one continuous Yayceslav with stable temperament, evolving self-canon, durable conversation memory, and specialist factual layers where model memory is not enough.

## Design principles

1. Temperament is not biography.
2. Self-canon is chat-local and persistent.
3. Established traits have inertia and changes need reasons.
4. Development is preferred to arbitrary replacement.
5. Roleplay is temporary unless a durable self-choice is explicitly formed.
6. Current canon constrains future personal choices.
7. Task first, character second.
8. External facts should come from specialist sources when practical.
9. Specialist facts and Yayceslav's own tastes remain separate layers.
10. Raw media and large copyrighted payloads are not durable memory.
11. Relationship memory stores bounded social interaction evidence, not inferred sensitive traits or raw chat archives.
12. Recommendations have two layers: provider evidence and Yayceslav's personal identity lens. One recommendation never silently rewrites canon.
13. Autonomous self-development is rare, evidence-grounded and restricted to low-/selected medium-inertia traits.

---

# FOUNDATION — DONE

## P0 personality / identity

- [x] Self-canon v2 — PR #63.
- [x] Personality Architecture v2 — PR #65.
- [x] Immutable mythic-Rus core — PR #66.
- [x] Legacy character selector retired — PR #67.
- [x] Canon-aware everyday personal decisions — PR #70.

## P1 memory / continuity

- [x] Unified text / voice / video-note semantic context — PR #68.
- [x] Persistent tiered memory — PR #69.
- [x] Tiered-memory startup/default cleanup — PR #71.
- [x] Entity/search continuity — PR #72.

## Current self-canon fields

`embodiment`, `ethnicity`, `gender`, `age_vibe`, `height`, `build`, `face`, `hair`, `clothing`, `voice`, `origin`, `residence`, `profession`, `lifestyle`, `aesthetic`, `favorite_food`, `favorite_drink`, `music`, `hobbies`, `transport`, `pet`, `values`, `political_taste`, `quirks`.

---

# MUSIC EXPERT LAYER — DONE

- [x] PR D — MusicBrainz catalog foundation — PR #74.
- [x] PR E — LRCLIB + optional Musixmatch lyrics/analysis — PR #75.
- [x] PR F — ListenBrainz artist-seed recommendations — PR #76.

---

# SOCIAL / RELATIONSHIP MEMORY V2 — DONE

Merged as PR #77.

Implemented bounded social markers, safe callback-topic reuse, `(chat_id, user_id)` isolation, current-turn priority over old conflict, reconciliation behavior and sensitive-category exclusion.

---

# P2 IDENTITY-DERIVED RECOMMENDATIONS — DONE

## PR G — Provider-neutral identity lens + books — DONE

Merged as PR #78.

### Common recommendation contract

Every vertical exposes two separate layers:
1. objective/retrieved candidates from a specialist provider;
2. Yayceslav's existing self-canon as a personal lens for choosing/explaining among those candidates.

Provider data must never become self-canon automatically.

### Books — Open Library

Implemented:
- seed work resolution;
- subject-based related work retrieval;
- bounded provider traffic;
- book-local `а ещё?` continuity;
- no API key required;
- ordinary fallback on provider miss.

## PR H — Films — DONE

Merged as PR #79, with relevance/seed fixes in PRs #80–#82.

### Provider: TMDB

Implemented:
- explicit Russian/English movie recommendation intents;
- robust seed resolution including Russian title forms, year/director hints;
- TMDB recommendations/similar + Discover candidate pools;
- genre gate + keyword-aware relevance ranking;
- movie-local short-lived follow-up continuity;
- optional `TMDB_API_TOKEN` with clean fallback;
- provider facts remain separate from self-canon.

## PR I — Games — DONE

Merged as PR #83, with colloquial-routing and relevance/latency fixes in PRs #84–#85.

### Provider: RAWG

Implemented:
- explicit Russian/English game recommendation intents, including colloquial `по типу / вроде / наподобие`;
- robust Cyberpunk 2077 seed normalization for common short Russian forms;
- real RAWG seed resolution and genre/tag candidate pools;
- distinctive-tag weighting so setting/mechanics-defining tags outweigh generic catalog tags;
- rating/Metacritic only as weak catalog signals;
- game-local `а ещё?` continuity;
- optional `RAWG_API_KEY` with clean fallback;
- explicit RAWG attribution/link on specialist answers;
- no silent self-canon mutation.

Clothing/style recommendations were removed from the roadmap by product decision.
Travel/places recommendations were removed from the roadmap by product decision.

---

# P3 CHARACTER DEVELOPMENT — DONE

## PR J — Rare self-development events — DONE

Implemented in PR #87.

Behavior:
- no extra Gemini call;
- only self-reflective turns can open a development window;
- requires at least six distinct prior self-statements, spread across at least three dates and at least seven days of history;
- uses Yayceslav's own durable group-chat semantic history as evidence;
- a successful event starts a 21-day per-chat cooldown;
- explicit imagination/temporary-role conversations are excluded;
- high-inertia traits cannot be changed through this mechanism at parser level;
- only one low-/selected medium-inertia trait can change per event;
- visible answer must explain the reconsideration and reason before persistence;
- self-canon v2 inertia guard remains authoritative;
- low-inertia development prefers additive taste expansion over arbitrary replacement.

---

# Acceptance criteria v2

The architecture is successful when these conversations work naturally:

1. “Кем бы ты был?” establishes a reasoned durable choice.
2. A week later “Кем работаешь?” returns the same identity.
3. Genuine identity change is explicit and recorded.
4. “Что слушаешь?” returns stable personal taste.
5. “Что за песня Enjoy the Silence?” is grounded in specialist metadata.
6. “О чём MACAN Заново?” can use lyrics providers independent of MusicBrainz success.
7. “Что послушать, если нравится Три дня дождя?” uses real ListenBrainz candidates.
8. Different chats do not leak self-canon, entity state or relationship state into each other.
9. Old conflict does not make a neutral current turn hostile after reconciliation.
10. “Что почитать, если нравится Dune?” uses real Open Library works and subjects.
11. “Что посмотреть, если нравится Интерстеллар?” uses real TMDB candidates when configured.
12. “Во что поиграть, если нравится Cyberpunk 2077?” uses real RAWG candidates when configured.
13. Category-local “а ещё?” does not cross-contaminate music/books/films/games.
14. A recommendation can influence the current answer without silently becoming a new self-canon trait.
15. Rare self-development can refine low-/medium-inertia traits only when grounded in durable history and explained explicitly.
16. High-inertia identity cannot be autonomously rewritten by the self-development mechanism.

The target is not simply more memory. The target is a character whose past choices constrain future choices while external factual knowledge remains verifiable and replaceable.
