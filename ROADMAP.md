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
- [x] Persistent tiered memory — PR #69.
- [x] Tiered-memory startup/default cleanup — PR #71.
- [x] Entity/search continuity — PR #72.

## Current self-canon fields

`embodiment`, `ethnicity`, `gender`, `age_vibe`, `height`, `build`, `face`, `hair`, `clothing`, `voice`, `origin`, `residence`, `profession`, `lifestyle`, `aesthetic`, `favorite_food`, `favorite_drink`, `music`, `hobbies`, `transport`, `pet`, `values`, `political_taste`, `quirks`.

The field count is sufficient. Future work should improve knowledge and behavior around these fields rather than adding many more slots.

---

# MUSIC EXPERT LAYER — DONE

- [x] PR D — MusicBrainz catalog foundation — PR #74.
- [x] PR E — LRCLIB + optional Musixmatch lyrics/analysis — PR #75.
- [x] PR F — ListenBrainz artist-seed recommendations — PR #76.

The music layer now separates:
- objective/retrieved music facts;
- lyrics/meaning context;
- similar-track/artist candidates;
- `self_canon.music` as Yayceslav's own taste.

---

# SOCIAL / RELATIONSHIP MEMORY V2 — DONE

Merged as PR #77.

Implemented:
- bounded structured social markers instead of raw chat archives;
- direct-to-Yayceslav markers for banter, correction, apology, gratitude, disagreement and reconciliation;
- reuse of safe member callback topics rather than duplicate topic storage;
- `(chat_id, user_id)` isolation;
- 365-day bounded marker lifetime;
- no extra Gemini classifier call;
- current message/current tone override old relationship history;
- old conflict cannot authorize hostility on a neutral current turn;
- reconciliation softens prior conflict;
- sensitive categories remain excluded from automatic social-memory inference.

---

# ACTIVE — P2 IDENTITY-DERIVED RECOMMENDATIONS

## PR G — Provider-neutral identity lens + books

### Common recommendation contract

Every vertical must expose two separate layers:
1. objective/retrieved candidates from a specialist provider;
2. Yayceslav's existing self-canon as a personal lens for choosing/explaining among those candidates.

The common identity lens is intentionally bounded to relevant existing fields such as `aesthetic`, `values`, `hobbies`, `lifestyle`, `quirks` and `music`. Provider data must never become self-canon automatically.

### Books — Open Library

Flow:

`explicit book recommendation intent -> Open Library seed work -> observed subjects -> Open Library related works -> provider-neutral identity lens -> Gemini/Yayceslav`

Capabilities:
- “что почитать, если нравится Мастер и Маргарита?”;
- “посоветуй 5 книг в духе Пикника на обочине”;
- `books like Dune`;
- resolve one seed work and its actual Open Library subjects;
- retrieve related works with bounded provider traffic;
- rank by subject overlap, using edition count only as a catalog prevalence signal, not quality;
- expose source links for candidates;
- keep book-specific short-lived follow-up continuity so “а ещё?” cannot accidentally reuse a music/entity seed;
- no Open Library API key required;
- provider miss falls through to ordinary answer/search behavior.

### Next verticals after books

- films;
- games;
- clothing/style;
- places/travel.

Each should be its own small provider adapter over the same identity-lens contract, not a new parallel personality/recommendation architecture.

---

# NEXT — P2

## Films vertical

Choose a provider with clear current API terms and useful movie identity/genre/keyword metadata. Keep provider evidence separate from personal reaction.

## Games vertical

Use a real catalog/metadata provider where API terms and key requirements make sense. Avoid model-memory-only game lists when specialist data is available.

## Clothing / style vertical

Recommendations should combine current products/availability with `aesthetic`, `clothing` and lifestyle canon, but purchases/brands never become durable taste automatically.

## Places / travel vertical

Current/local facts must come from current place/travel sources; `aesthetic`, `lifestyle`, `values` and hobbies may influence Yayceslav's personal pick only.

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
10. “Что послушать, если нравится Три дня дождя?” uses real ListenBrainz candidates.
11. “Тебе самому что из этого ближе?” uses self-canon as a personal lens rather than a provider fact.
12. Different chats do not leak self-canon, entity state or relationship state into each other.
13. Old conflict does not make a neutral current turn hostile after apology/reconciliation.
14. Safe recurring social callbacks feel continuous without becoming a fake biography.
15. “Что почитать, если нравится Dune?” uses real Open Library works and subjects.
16. After a music recommendation, “а ещё?” does not accidentally enter the books route.
17. A recommendation can influence the current answer without silently becoming a new self-canon trait.

The target is not simply more memory. The target is a character whose past choices constrain future choices while external factual knowledge remains verifiable and replaceable.
