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

## PR D — Music catalog foundation — DONE

### Provider: MusicBrainz

Implemented:
- artist identity and canonical MBID;
- recordings/tracks;
- releases/release groups/albums;
- dates and artist credits where available;
- local deterministic music intent detection with no classifier model call;
- polite provider spacing and bounded RAM cache;
- chat-local entity continuity for short music follow-ups;
- specialist facts kept separate from `self_canon.music`.

Merged as PR #74.

---

## PR E — Lyrics + analysis — ACTIVE

### Provider chain

`LRCLIB -> optional Musixmatch -> existing real web-search fallback`

LRCLIB is the primary provider and must work even when MusicBrainz does not resolve the track. MusicBrainz metadata is optional enrichment, not a prerequisite for lyrics lookup.

Musixmatch is a secondary provider when `MUSIXMATCH_API_KEY` is configured. The bot must remain fully operational without that key.

### Capabilities

- identify lyrics from `track + artist` when catalog metadata is available;
- free-text lyrics search from a raw user query when MusicBrainz is missing a fresh/local release;
- retrieve plain/synchronized lyrics from LRCLIB when available;
- use Musixmatch only after LRCLIB misses;
- answer “о чём песня?”, “про что трек?”, “что означает эта строка?” from retrieved lyrics;
- use the existing real-search path only after specialist providers fail;
- never ask Gemini to invent lyrics from model memory.

### Russian-language acceptance set

The regression set must include Cyrillic and modern Russian-language music, including representative query shapes such as:
- `MACAN Заново`;
- `Три дня дождя Отпускай`;
- artist + track written entirely in Cyrillic;
- mixed Latin/Cyrillic artist names;
- `feat.` / collaborations;
- same-title songs where artist identity is required;
- a fresh Russian release absent from MusicBrainz but present in a lyrics provider.

### Matching safeguards

- exact `track + artist` match wins when available;
- album/duration are additional evidence, not mandatory for raw fallback search;
- reject a weak one-word same-title match without an independently resolved artist;
- do not merge lyrics from another artist’s song with the same title;
- provider failures/rate limits must degrade to the next provider, not break the music handler.

### Copyright / storage

- never persist full lyrics to SQLite;
- short bounded RAM cache only;
- full retrieved lyrics are internal analysis context, not normal output;
- prefer summary/analysis over reproduction;
- if a quote is genuinely needed for explanation, keep it to one short line/phrase;
- a request for the full lyrics should not dump the copyrighted text.

### Self-canon separation

- lyrics providers answer what the song says;
- `self_canon.music` answers whether Yayceslav personally likes it and why;
- retrieving/analyzing a song never silently adds it to his personal taste.

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
9. “О чём MACAN Заново?” may resolve lyrics even if MusicBrainz has no useful match.
10. “О чём она?” stays on the same resolved track and uses retrieved lyrics rather than model memory.
11. “Тебе самому нравится?” is grounded in self-canon rather than specialist metadata.
12. Text, voice, video-note and explicit search follow-ups maintain the same recent entity/topic when appropriate.
13. Different chats do not leak self-canon, entity state or relationship state into each other.

The target is not simply more memory. The target is a character whose past choices constrain future choices while external factual knowledge remains verifiable and replaceable.
