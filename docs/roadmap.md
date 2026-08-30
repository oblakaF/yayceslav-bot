# Public roadmap

This roadmap describes the public direction of Yayceslav without exposing private deployment data, user information, operational secrets, or every internal experiment.

## Stable foundation

The current public codebase already includes:

- Telegram group/private routing;
- Gemini-backed responses;
- bounded conversational and social memory;
- reputation and relationship context;
- voice/media handling;
- bounded web-search enrichment;
- sticker behavior and anti-spam pacing;
- conflict FSM and fight-aware routing;
- contextual roast planning with repetition, contradiction and self-own targeting;
- regression tests and CI on Python 3.12/3.13.

## Near-term validation

Before expanding the social architecture further, the current fight behavior should be validated in real Telegram conversations as a complete sequence rather than as isolated unit tests.

Important checks include:

- escalation should not happen too early;
- replies should stay grounded in what the target actually wrote;
- the bot should not recycle the same punch repeatedly;
- stickers and delayed follow-ups should remain bounded;
- reconciliation and serious topics should stop pending aggression;
- no sensitive claim should silently become a biographical fact.

## Next research direction

### 1. Social Scene Graph

Model short-lived interactions between participants, not only each participant's relationship with the bot. Candidate signals include replies, mentions, reactions, support, opposition and attention. Edges should decay over time and remain bounded.

### 2. Scene-aware conversation

Allow routing and fight logic to consume the current social scene: who is supporting whom, who changed sides, who joined a dispute, and whether the group is reacting to a particular message.

### 3. Turn Actor: REPLY / WAIT / PASS / REACT

Treat silence, waiting and emoji reactions as first-class actions. Burst messages from one person can be briefly grouped so the bot responds to the complete thought instead of racing every individual message.

### 4. Feedback learning

Use repeated social evidence rather than one-off reactions to tune behavior. Potential evidence includes reactions, quotes, follow-up jokes, explicit negative feedback and owner feedback. Candidate preferences should require repeated confirmation and support rollback.

### 5. Episode memory

Represent selected conversations as bounded events rather than only isolated facts: participants, topic, notable contradiction, resolution, and later callback value.

## Resource constraints

The project is intentionally designed for a small single-service deployment:

- SQLite instead of a separate database service where practical;
- bounded RAM state with TTLs;
- no local LLM;
- no vector database by default;
- no unbounded raw transcript archive;
- no extra Gemini call merely to classify tone when deterministic context already exists.

Future private production work may move faster than this public roadmap. Public releases will be curated rather than treated as a mirror of all experiments.
