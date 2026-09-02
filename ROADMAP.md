# Yayceslav Roadmap

This roadmap captures the architecture discussed after the September 2026 live-chat review. The goal is not to add more isolated prompt patches; it is to make Yayceslav feel like one continuous person with memory, reasons for his choices, coherent tastes, and reliable expert knowledge where external sources are needed.

## Design principles

1. **Temperament is not biography.**
   The base personality defines stable temperament: useful, self-confident, curious, ironic, conversational, capable of arguing, capable of admitting mistakes, not bureaucratic, and not obliged to agree with users. It should not define mutable biography such as ethnicity, profession, music taste or place of residence.

2. **Self-canon is chat-local and persistent.**
   Each chat can develop its own version of Yayceslav. Canon survives restarts via SQLite. A different chat may develop a different biography and taste profile.

3. **Personality has inertia.**
   An established trait must not be silently overwritten because a later question is phrased differently. Existing traits are the default answer until Yayceslav genuinely reconsiders them.

4. **Changes need reasons.**
   If Yayceslav changes an established high- or medium-inertia trait, the response should contain a natural reconsideration such as: “Знаешь, я подумал… раньше выбрал X, но теперь Y кажется мне ближе, потому что Z.” The runtime records both the new value and the reason for revision.

5. **Development is preferred to replacement.**
   New tastes can broaden existing tastes instead of replacing them. Example: darkwave + jazz can become a broader music profile unless Yayceslav explicitly says he no longer identifies with the old preference.

6. **Roleplay is not biography.**
   A one-message role (“сегодня ты рэпер”, “представь себя пилотом”) must not automatically enter self-canon.

7. **Current canon influences future choices.**
   New decisions should be made as the already-established Yayceslav, not as independent random generations.

8. **Task first, character second.**
   Persona may color an answer, but it must not replace a useful answer with refusal, a punchline, or “гугли сам”.

9. **External facts come from specialist sources.**
   Music metadata, lyrics and recommendation data should be retrieved from dedicated sources instead of relying on model memory.

---

# DONE

## Live-chat routing fixes

- Fixed quoted/narrated third-party hostility being misread as a direct attack.
- Added opt-in imagination mode for hypothetical self-image and preference questions.
- Added real political-choice handling for hypothetical persona choices without inventing fake parties.
- Added self-portrait mode: “опиши себя”, “кто ты”, “каким ты себя видишь”.
- Added chat-local persistent self-canon with 24 independent traits and revision history.
- Added voice live bridge:
  - profanity alone is not hostility;
  - task completion is prioritized over persona flourish;
  - corrected named entities beat bad ASR guesses;
  - short spoken follow-ups get 15-minute / 4-turn RAM context;
  - voice preference choices can update the same self-canon;
  - direct useful voice answers are no longer constrained by the old ~1000-character path.

## Current self-canon fields

- embodiment
- ethnicity
- gender
- age_vibe
- height
- build
- face
- hair
- clothing
- voice
- origin
- residence
- profession
- lifestyle
- aesthetic
- favorite_food
- favorite_drink
- music
- hobbies
- transport
- pet
- values
- political_taste
- quirks

The field count is sufficient. The next work should improve semantics and stability, not add many more slots.

---

# NEXT — P0

## 1. Self-canon v2: identity inertia and reasons

### Goal
Turn self-canon from a mutable key/value store into a believable evolving identity.

### Data model
Extend each active canon trait with metadata:

- `trait_value`
- `reason` — why Yayceslav chose it
- `inertia` — high / medium / soft
- `confidence` or `commitment` — how settled the choice is
- `revision`
- `updated_at`

Extend history with:

- old value
- new value
- old reason
- new reason
- explicit revision reason
- source excerpt

### Inertia classes

**High inertia**
- embodiment
- ethnicity
- gender
- age_vibe
- height
- build
- face
- hair
- origin
- profession

These should change rarely and only after explicit reconsideration with a reason.

**Medium inertia**
- residence
- clothing
- lifestyle
- aesthetic
- transport
- pet
- values
- political_taste
- voice

These may evolve, but a replacement still needs an intelligible reason.

**Soft / additive**
- favorite_food
- favorite_drink
- music
- hobbies
- quirks

These should usually expand or refine rather than replace previous preferences.

### Runtime behavior

If a trait is unset:
- choose freely;
- provide a natural reason;
- save value + reason.

If a trait is already set and the user simply asks again:
- recall and answer consistently;
- do not rewrite canon.

If the user proposes another option:
- Yayceslav may reject it based on current identity;
- no update unless he genuinely changes his mind.

If Yayceslav changes an established trait:
- response must explicitly acknowledge reconsideration;
- reason must be present;
- runtime records the revision event.

For soft/additive traits:
- allow “also”, “started liking”, “added to my taste” updates;
- do not erase earlier preferences unless Yayceslav explicitly rejects them.

### Regression examples

- `profession=электрик` + “А программистом не хотел бы?” -> may remain electrician with rationale.
- `profession=электрик` + genuine reconsideration -> can become automation engineer only with reason.
- `music=darkwave` + “а джаз?” -> may become `darkwave + jazz`, not random replacement.
- “Сегодня ты рэпер” -> no persistent music/profession rewrite.
- “Кем бы ты работал?” repeated later -> same answer, naturally recalled.

---

## 2. Personality architecture v2

### Goal
Make `personality.py` the stable temperament layer rather than the whole identity.

### Stable core temperament
Yayceslav should remain:

- useful before performative;
- self-confident but not omniscient;
- curious and willing to have preferences;
- ironic and conversational;
- capable of disagreeing with users;
- capable of saying “я ошибся” without robotic apology language;
- socially aware in group chat;
- resistant to bureaucratic/meta “я программа / я алгоритм” evasions in imagination scenes;
- able to continue a shared absurd scene instead of constantly resetting to literal reality.

### Layering
System prompt should clearly separate:

1. **Temperament core** — stable across chats.
2. **Chat-local self-canon** — biography, appearance, tastes, values.
3. **Relationship/social state** — how he relates to individual chat members.
4. **Current mood / conversation mode** — temporary.
5. **Voice pack / style pack** — presentation only.
6. **Roleplay/imagination scene** — temporary unless a durable self-choice is explicitly formed.

No voice pack or temporary mode should silently rewrite identity.

---

## 3. Canon-aware decision making

### Goal
New preferences must be inferred from the existing persona.

Examples:

If Yayceslav is already an electrician from panel housing, minimalist, likes darkwave and practical technology, then “what car would you buy?” should be answered as that person rather than as a fresh random draw.

Implementation:
- inject current canon before imagination choice rules;
- tell the model to prefer options coherent with existing traits;
- allow surprising choices only when it can explain why they still fit or why his view changed.

Add regressions that test coherence across multiple independent trait questions.

---

# NEXT — P1

## 4. Unified text / voice / video-note conversation context

Current voice bridge keeps only voice-to-voice short context. Next step is one short semantic conversation bridge across modalities.

### Goal
These should all work:

- text -> voice -> text
- voice -> text -> voice
- video-note -> voice follow-up
- text entity correction -> voice follow-up

### Constraints

- do not persist raw audio;
- do not persist raw video;
- short semantic summaries only;
- recent context expires;
- persistent facts still go through the existing memory systems, not this bridge.

### Group-chat speaker awareness
Use two context levels:

1. same-speaker recent context — strongest;
2. shared-chat recent context — fallback when the continuation clearly belongs to the group topic.

This prevents one member saying “а дальше?” from accidentally inheriting another person’s unrelated private topic while still supporting natural group conversation.

### Regression scenarios

- text Marvel question -> voice “а вторая фаза?” -> text “а фильмы там какие?”
- user A discusses Marvel; user B starts BMW tires -> no topic contamination
- video-note “это мой кот” -> voice “сколько ему лет?” -> resolves `ему` to the cat
- corrected entity persists across modality switch

---

## 5. Entity and search continuity

### Goal
Make named entities stable across ASR corrections and searches.

- current explicit correction beats previous ASR interpretation;
- search query must belong to the current turn;
- previous unrelated artist/person/movie must never leak into a new search;
- uncertain proper names trigger entity resolution or one short clarification, not confident fabrication.

Add a tiny short-lived resolved-entity context rather than relying only on prose prompt history.

---

# NEXT — P1/P2: MUSIC EXPERT LAYER

## 6. Dedicated `music_runtime.py`

### Goal
When users ask about artists, tracks, albums, lyrics or music recommendations, Yayceslav should use real music data and then answer in character.

### Initial providers

**MusicBrainz**
- artist identity
- recordings
- releases/albums
- dates
- credits/relationships where available
- canonical MBIDs for entity resolution

**LRCLIB**
- lyrics retrieval for identified tracks
- plain lyrics and synchronized lyrics where available

**ListenBrainz**
- listening/popularity signals
- similar artists/recordings
- recommendation support

Optional later:
- Last.fm tags/community similarity if an API key and terms are acceptable.

### Router

`user -> music intent -> entity resolver -> specialist APIs -> normalized music context -> Gemini/Yayceslav`

Do not route ordinary music questions through generic web search first when the specialist sources can answer them.

### Capabilities

- “кто это поёт?”
- “из какого альбома?”
- “какого года?”
- “кто написал?” where source metadata supports it
- “о чём эта песня?” using retrieved lyrics
- “что означает эта строка?”
- “какие у них самые известные/типичные вещи?” using available popularity/listening data
- “на кого похоже?”
- “что посоветуешь, если нравится X?”
- discography and release navigation
- compare two artists/tracks using retrieved metadata and lyrics-derived analysis

### Copyright / storage behavior

- do not store full copyrighted lyrics permanently in SQLite;
- cache externally retrieved lyrics only briefly if needed for performance;
- use lyrics for analysis and identification;
- avoid dumping entire lyrics when a summary/analysis answers the request.

### Music + self-canon

Music knowledge and Yayceslav’s own taste are separate:

- music APIs provide facts;
- `self_canon.music` provides his personal taste;
- recommendations and opinions should combine both.

Example: if his canon says darkwave/industrial/post-punk, he may still accurately explain mainstream pop but should express his personal reaction consistently.

---

# LATER — P2

## 7. Identity-derived recommendation engine

Use canon + specialist knowledge to make recommendations “as Yayceslav”:

- music
- films
- books
- games
- clothing/style
- places/travel

A recommendation should expose both:
- objective/retrieved evidence;
- his own stable preference.

Do not silently turn a recommendation into a new self-canon trait unless he explicitly decides it becomes part of his identity.

---

## 8. Self-development events

Optional later feature: rare explicit self-reflection events generated from accumulated canon/history.

Examples:
- “я раньше думал X, но после наших разговоров понял Y”
- consolidating overlapping music tastes
- refining profession/lifestyle choices

Constraints:
- rare;
- grounded in actual stored history;
- not random personality churn;
- never rewrite high-inertia traits without a visible reason.

---

# Implementation order

## PR A — Self-canon v2 schema + rules

- migration for reason/inertia/commitment metadata;
- history reason fields;
- compatibility with existing 24 stored traits;
- no data loss;
- update protocol v2;
- tests for no-flip behavior and justified revision.

## PR B — Personality architecture v2

- reduce base personality to temperament;
- explicit prompt layering;
- canon-aware decision rule;
- regressions from the September live chat.

## PR C — Unified multimodal short context

- text/voice/video semantic bridge;
- same-speaker priority in groups;
- shared-chat fallback;
- entity correction continuity;
- TTL and privacy tests.

## PR D — Music catalog foundation

- `music_runtime.py`;
- MusicBrainz client with rate-limit-safe cache;
- entity resolution;
- artist/track/album metadata;
- tests with mocked provider responses.

## PR E — Lyrics + analysis

- LRCLIB adapter;
- track matching safeguards;
- lyric-analysis context;
- no permanent full-lyrics persistence;
- copyright-safe output behavior tests.

## PR F — ListenBrainz recommendations

- similar artists/recordings;
- popularity/listening signals;
- combine data with `self_canon.music` for Yayceslav-specific recommendations.

---

# Acceptance criteria

The architecture is successful when these conversations feel natural:

1. “Кем бы ты был?” -> establishes a reasoned choice.
2. A week later “Кем работаешь?” -> same identity without regeneration.
3. “А программистом?” -> he can reject the suggestion based on his own established reasons.
4. If he genuinely changes profession, he explicitly explains why and history records the transition.
5. “Что слушаешь?” -> stable taste.
6. “А джаз?” -> taste can expand rather than randomly flip.
7. “Что за песня Enjoy the Silence?” -> real metadata source.
8. “О чём она?” -> analysis grounded in retrieved lyrics.
9. “Тебе самому нравится?” -> opinion grounded in his own canon rather than model randomness.
10. Text, voice and video follow-ups refer to the same recent conversation naturally.
11. Different chats can develop different Yayceslav identities without leaking canon between them.

The target is not a bot that remembers more fields. The target is a character whose past choices constrain and explain his future choices.