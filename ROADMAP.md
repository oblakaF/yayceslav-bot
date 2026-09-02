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

# MUSIC EXPERT LAYER — DONE

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

## PR E — Lyrics + analysis — DONE

### Provider chain

`LRCLIB -> optional Musixmatch -> existing real web-search fallback`

Implemented:
- LRCLIB exact `track + artist` matching when catalog metadata exists;
- LRCLIB raw free-text search when MusicBrainz does not know a fresh/local release;
- optional Musixmatch fallback through `MUSIXMATCH_API_KEY`;
- modern Cyrillic regression cases including `MACAN Заново` and `Три дня дождя Отпускай`;
- same-title safeguards;
- no durable full-lyrics storage;
- lyrics used only as analysis context;
- specialist failures degrade to the next source.

Merged as PR #75.

---

## PR F — Music recommendations — DONE

### Provider: ListenBrainz

Implemented flow:

`user recommendation intent -> MusicBrainz artist MBID -> ListenBrainz LB Radio -> batch recording metadata -> self_canon.music preference lens -> Gemini/Yayceslav`

Capabilities:
- “что послушать, если нравится X?”;
- “на кого похож X?”;
- “дай несколько треков в духе X”;
- similar artists/recordings based on ListenBrainz data;
- `total_listen_count` used only as a popularity/listening signal, not quality;
- batch metadata lookup for recording names, artists and tags;
- exclude the seed artist from ordinary similarity recommendations;
- combine factual candidates with `self_canon.music` so Yayceslav can say what he personally would choose;
- Cyrillic seeds including `Три дня дождя` and `MACAN`;
- no ListenBrainz user account/token required for ordinary artist-seed recommendations.

Merged as PR #76.

---

# ACTIVE — P2 SOCIAL / RELATIONSHIP MEMORY V2

Goal: improve long-term relationship continuity without turning the bot into surveillance memory.

Implementation direction:
- reuse existing `chat_member_profiles`, safe member callback terms, pairwise interaction statistics and relationship/conflict data;
- persist only bounded structured social markers, not raw messages;
- social markers include mutual banter, corrections, apologies, gratitude, explicit disagreement and reconciliation;
- current message/current tone always override historical relationship state;
- reconciliation softens old conflict instead of creating permanent grudges;
- recurring callback topics can be used sparsely but never treated as preferences, professions, beliefs or personality traits;
- automatic durable relationship memory excludes health, finance, politics, religion, sexuality and other sensitive characteristics;
- strict `(chat_id, user_id)` isolation with regression tests against cross-user/cross-chat contamination;
- no extra Gemini classifier call.

Acceptance examples:
- after several playful exchanges, a playful current turn may get a more familiar callback;
- after the user corrected Yayceslav earlier, a relevant future correction can be acknowledged naturally instead of pretending infallibility;
- after apology/reconciliation, old hostility must not keep poisoning neutral replies;
- a recurring safe topic may be remembered as something the member has actually discussed, not as a stable personal trait;
- an unrelated member or another group must never inherit this relationship history.

---

# NEXT — P2

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
11. “Что послушать, если нравится Три дня дождя?” uses real ListenBrainz candidates.
12. “Тебе самому что из этого ближе?” uses `self_canon.music` as a personal lens rather than a provider fact.
13. Text, voice, video-note and explicit search follow-ups maintain the same recent entity/topic when appropriate.
14. Different chats do not leak self-canon, entity state or relationship state into each other.
15. Old conflict does not make a neutral current turn hostile after apology/reconciliation.
16. Safe recurring social callbacks feel continuous without becoming a fake biography.

The target is not simply more memory. The target is a character whose past choices constrain future choices while external factual knowledge remains verifiable and replaceable.