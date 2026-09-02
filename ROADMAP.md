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

---

# FOUNDATION — DONE

## P0 personality / identity

- [x] Self-canon v2: reasons, inertia, commitment and guarded revisions — PR #63.
- [x] Personality Architecture v2: task > temperament > self-canon > scene > style — PR #65.
- [x] Immutable mythic-Rus core: ведает / mythological lizards without making it a selectable style — PR #66.
- [x] Legacy character selector retired — PR #67.
- [x] Canon-aware everyday personal decisions — PR #70.

## P1 memory / continuity

- [x] Unified text / voice / video-note semantic context — PR #68.
- [x] Persistent tiered memory:
  - 2h / 60-message working RAM;
  - 30-day bounded semantic SQLite history;
  - local FTS retrieval;
  - 90-day compact digests;
  - 365-day notable episodic memory — PR #69.
- [x] Tiered-memory startup/default cleanup — PR #71.
- [x] Entity/search continuity with a short-lived chat-local resolved topic — PR #72.

## Current self-canon fields

`embodiment`, `ethnicity`, `gender`, `age_vibe`, `height`, `build`, `face`, `hair`, `clothing`, `voice`, `origin`, `residence`, `profession`, `lifestyle`, `aesthetic`, `favorite_food`, `favorite_drink`, `music`, `hobbies`, `transport`, `pet`, `values`, `political_taste`, `quirks`.

The field count is sufficient. Future work should improve knowledge and behavior around these fields rather than adding many more slots.

---

# ACTIVE — P1/P2 MUSIC EXPERT LAYER

## PR D — Music catalog foundation

### Goal
Create a dedicated `music_runtime.py` so ordinary artist/track/album questions use real music metadata before generic web search.

### Provider: MusicBrainz

Initial scope:
- artist identity and canonical MBID;
- recordings/tracks;
- releases/release groups/albums;
- dates;
- artist credits and relationships where available;
- disambiguation between same/similar names.

### Router

`user -> music intent -> music entity resolver -> MusicBrainz -> normalized music context -> Gemini/Yayceslav`

Constraints:
- no extra Gemini call just to classify music intent;
- bounded provider requests;
- polite MusicBrainz user-agent;
- short TTL in-memory cache initially;
- fall back safely when provider is unavailable;
- music facts never overwrite `self_canon.music`.

### Acceptance examples

- “кто поёт Enjoy the Silence?”
- “из какого она альбома?”
- “какого года?”
- “что ещё есть у Depeche Mode?”
- ambiguous artist names resolve conservatively instead of confident fabrication.

---

## PR E — Lyrics + analysis

### Provider: LRCLIB

Capabilities:
- identify lyrics only after track/artist resolution;
- retrieve plain/synchronized lyrics when available;
- answer “о чём песня?” and “что означает эта строка?” from retrieved text;
- avoid permanent full-lyrics SQLite storage;
- keep output copyright-safe: analysis/summary over full reproduction.

Safeguards:
- track/artist matching before accepting lyrics;
- do not merge lyrics from a same-title different song;
- brief cache only if needed.

---

## PR F — Music recommendations

### Provider: ListenBrainz

Capabilities:
- similar artists/recordings;
- available listening/popularity signals;
- recommendation candidates based on real catalog entities;
- combine factual candidates with `self_canon.music` for Yayceslav-specific opinions.

Optional later:
- Last.fm tags/community similarity if API terms/key make sense.

Important separation:
- specialist APIs answer “what is this / who made it / what is similar?”;
- `self_canon.music` answers “does Yayceslav personally like it and why?”

---

# NEXT — P2

## Social / relationship memory v2

Improve long-term relationship continuity without turning the bot into surveillance memory.

Goals:
- better use of existing reputation, affinity, relationship and episodic data;
- remember recurring shared jokes and meaningful conflicts, not every message;
- distinguish a person's long-term relationship state from the current mood/fight;
- callbacks must be sparse and relevant;
- sensitive content remains excluded from automatic durable member memory.

Potential implementation:
- bounded relationship summaries derived from already-stored events;
- no raw full-chat archive per member;
- explicit regression tests for cross-user contamination.

## Identity-derived recommendation engine

Extend the same pattern beyond music:
- films;
- books;
- games;
- clothing/style;
- places/travel.

Recommendations should expose two layers:
1. objective/retrieved evidence;
2. Yayceslav's stable personal reaction.

A recommendation must not silently become a self-canon trait.

## Rare self-development events

Optional later feature:
- rare explicit reflection grounded in actual canon/history;
- “раньше думал X, теперь Y, потому что Z”;
- consolidate additive tastes without random personality churn;
- never rewrite high-inertia traits invisibly.

---

# Acceptance criteria v2

The architecture is successful when these conversations work naturally:

1. “Кем бы ты был?” establishes a reasoned durable choice.
2. A week later “Кем работаешь?” returns the same identity.
3. “А программистом?” can be rejected based on established reasons.
4. Genuine identity change is explicit and recorded.
5. “Что слушаешь?” returns stable personal taste.
6. “А джаз?” can expand taste rather than randomly flip it.
7. “Что за песня Enjoy the Silence?” is grounded in specialist metadata.
8. “Из какого она альбома?” keeps the resolved track/entity.
9. “О чём она?” is grounded in retrieved lyrics rather than model memory.
10. “Тебе самому нравится?” is grounded in self-canon rather than specialist metadata.
11. Text, voice, video-note and explicit search follow-ups maintain the same recent entity/topic when appropriate.
12. Different chats do not leak self-canon, entity state or relationship state into each other.

The target is not simply more memory. The target is a character whose past choices constrain future choices while external factual knowledge remains verifiable and replaceable.