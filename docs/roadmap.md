# Yayceslav master roadmap

This document is the current roadmap and execution order for the public Yayceslav project. It is intentionally detailed enough to preserve the development plan while avoiding production secrets, private user data, live databases, credentials, or raw private chat exports.

## Status legend

- ✅ **DONE** — implemented and covered by tests; live behavior may still need observation.
- 🟡 **VALIDATE / TUNE** — code exists, but real Telegram behavior must still be evaluated.
- ⬜ **PLANNED** — agreed future work, not started yet.
- ⏸️ **DEFERRED** — intentionally postponed until a later explicit decision.

## 0. Current operating mode

### Public repository remains the source of truth — ✅

For now, `oblakaF/yayceslav-bot` remains:

- the active development repository;
- the source of truth for production code;
- the repository used for pull requests and CI;
- the repository connected to the live Railway deployment through `main`.

The private repository `oblakaF/yayceslav-core` exists only as a future placeholder. It is **not** the active development repository, is **not** the Railway source, and should not receive production-only development until a separate migration decision is made.

### Production engineering rules

The project should continue to preserve these constraints:

- one stateful production owner per concern;
- support layers may enrich an owner but must not silently create a second state machine;
- no extra Gemini call merely to classify tone when deterministic context already exists;
- serious/sensitive context has priority over comedy, aggression and social games;
- persistent data should stay compact and auditable;
- RAM state must be bounded by TTLs and size limits;
- SQLite remains the default persistence layer;
- no local LLM, vector database, Redis, or unbounded raw transcript archive unless a concrete need justifies the extra infrastructure;
- private tokens, live user databases and raw private chat exports must never be committed.

## 1. Stabilize the existing Fight / RAGE system

### 1.1 Current implementation — ✅

The current conflict stack already includes:

- persistent social baseline separated from temporary conflict state;
- a single conflict FSM;
- fight-aware routing;
- compact RAGE answers;
- contextual roast planning;
- repetition detection;
- contradiction and self-own detection across multiple opponent messages;
- anti-repeat tracking for used angles and hooks;
- bounded fight memory;
- fight-aware stickers with pacing and caps;
- optional delayed second punch;
- one-shot post-fight afterburner;
- reconciliation cancellation;
- serious-topic cancellation;
- sensitive-claim guards;
- long-fight sequence regression coverage.

### 1.2 Live Telegram fight validation — 🟡 NEXT

Before adding a new social architecture, test the current fight stack as one complete live sequence rather than as isolated unit tests.

Recommended live scenarios:

1. **Gradual escalation** — light banter should not jump into hard RAGE too early.
2. **Long argument** — the opponent repeats a point, changes position, contradicts themselves, or says that they do not care while continuing to argue.
3. **Visible self-own** — examples such as “I am leaving / I will not answer anymore” followed by more replies.
4. **Disengagement** — the target stops replying or moves on to other people.
5. **Reconciliation** — “okay, enough / let’s drop it” must cancel pending aggression.
6. **Serious-topic pivot** — an argument that suddenly becomes a real factual or sensitive question must leave fight mode cleanly.

Evaluate the whole sequence for:

- contextual grounding in the opponent’s real words;
- quality of contradiction/self-own selection;
- brevity and rhythm;
- generic-vs-specific punch ratio;
- joke repetition;
- profanity becoming content instead of merely tone;
- sticker timing and frequency;
- delayed-punch usefulness;
- afterburner usefulness;
- correct disengagement;
- no invented biography, diagnosis, intimate preference, or other unsupported personal fact;
- no aggression bleeding into a reconciled or serious turn.

### 1.3 Final fight tuning — 🟡 CONDITIONAL

Only fix problems that actually appear in the live transcript. Classify each failure as one of:

- deterministic code/routing;
- prompt quality;
- pacing/timing;
- model randomness;
- missing evidence/context.

Do not add another parallel conflict layer merely because one generated line is weak.

### 1.4 Fight System v1 Stable — ⬜

Mark the fight system stable when:

- the live sequence behaves coherently from escalation to disengagement;
- reconciliation and serious pivots reliably stop pending aggression;
- callbacks remain grounded;
- repetition is acceptably low;
- no additional owner/state machine is needed.

## 2. Public GitHub housekeeping

### 2.1 Repository presentation — ✅ MOSTLY DONE

The public repository already has:

- redesigned README;
- source-available proprietary `LICENSE`;
- `COPYRIGHT.md`;
- `TRADEMARKS.md`;
- `SECURITY.md`;
- `CONTRIBUTING.md`;
- `CHANGELOG.md`;
- public architecture/deployment/roadmap documentation;
- PR and issue templates;
- simplified CI targeting `main`.

### 2.2 GitHub repository settings — ⬜

Still desirable at the repository-settings level:

- add a concise repository Description;
- add relevant Topics (`telegram-bot`, `telegram`, `python`, `gemini`, `llm`, `ai-agent`, `social-agent`, `conversational-ai`);
- protect `main`;
- require the CI checks before merge;
- enable automatic deletion of merged head branches once historical-branch cleanup is considered safe.

Do **not** mass-delete historical branches yet solely for visual cleanliness. They remain useful as development history until the future private/archive strategy is finalized.

### 2.3 GitHub Actions storage — ⬜ HOUSEKEEPING

Investigate the account-level Actions/Packages storage usage. The current main CI does not intentionally upload workflow artifacts, so old artifacts/packages should be identified before changing the test strategy.

Do not weaken CI simply to avoid storage usage; prefer deleting stale artifacts/packages and keeping the current compile + pytest checks.

## 3. Social Scene Graph v1 — ⬜

### Goal

Move from primarily understanding `Yayceslav ↔ person` relationships to understanding the **temporary social scene between multiple group participants**.

The graph must describe what is happening *now*, not permanently label people.

### Candidate short-lived edges

Examples:

- `A -> attention -> B`
- `A -> support -> B`
- `A -> oppose -> B`
- `A -> joke-with -> B`
- `A -> amusement -> B`

### Evidence sources

Start with deterministic Telegram metadata and existing classifiers rather than a new Gemini call:

- reply-to relationships;
- direct mentions;
- directed hostility;
- positive/supportive replies;
- reactions;
- repeated conversational attention;
- timing and turn sequence.

### Constraints

- bounded RAM or compact SQLite only where persistence is genuinely useful;
- weights decay over time;
- current-scene state must not silently become a permanent personality claim;
- no global social inference from one isolated reply/reaction;
- no extra model call per message solely to build graph edges.

### Definition of done

Yayceslav can reliably answer questions such as:

- who is currently arguing with whom;
- who joined whose side;
- who is repeatedly defending another participant;
- who the current audience is reacting to;
- whether the apparent coalition changed during the scene.

## 4. Scene-aware conversation and fights — ⬜

Once the graph is stable, expose a small, bounded summary of the current scene to routing and roast planning.

### New capability: social-own

Current fight intelligence detects a **self-own** when a person contradicts themselves. The next step is a **social-own**: a person’s statement visibly conflicts with what the group is doing around them.

Examples:

- someone says “nobody cares” while several people are actively replying to the target idea;
- someone claims to be alone in an argument while another participant repeatedly defends them;
- someone claims “everyone agrees with me” while the scene graph shows active opposition;
- someone changes sides while pretending their position never changed.

### Behavioral use

Scene state should help Yayceslav choose among:

- reply;
- shorter reply;
- stay out because the target is already being piled on;
- use a social callback;
- acknowledge an ally;
- stop behaving as though Yayceslav “won” when the room clearly disagrees.

The scene graph is context, not a second conflict state machine.

## 5. Turn Actor: REPLY / WAIT / PASS / REACT — ⬜

### Goal

Stop treating every incoming Telegram message as an independent completed conversational turn.

### Actions

- **REPLY** — answer now.
- **WAIT** — likely message burst; briefly wait for the speaker to finish.
- **PASS** — do not intervene.
- **REACT** — an emoji reaction is sufficient; do not send text.

### Burst handling

If one participant sends several short messages within a very small window, group them into one cognitive turn where appropriate.

Instead of:

`message 1 -> model call`

`message 2 -> model call`

`message 3 -> model call`

prefer:

`message 1 + message 2 + message 3 -> one coherent turn -> one model call`

### Expected benefit

- fewer interruptions;
- better context;
- fewer duplicate or obsolete replies;
- potentially fewer Gemini calls;
- more human timing;
- better handling of multi-message arguments.

### Constraints

- bounded wait window;
- no long blocking queue;
- new incoming context must be able to invalidate an obsolete pending answer;
- serious/high-priority messages must not be unnecessarily delayed.

## 6. Telegram reactions as first-class behavior — ⬜

Add reactions such as `😂`, `💀`, `👀`, `🔥`, `👍` as a deliberate social action between silence and a full text response.

### Why

Sometimes a reaction is more human and less intrusive than another generated sentence.

Examples:

- obvious self-own -> `💀` may be stronger than explaining the joke;
- funny participant message -> `😂`;
- suspicious claim -> `👀`;
- achievement/good result -> `🔥` or `👍`.

### Integration

Reaction behavior should:

- have strict frequency limits;
- respect serious/sensitive context;
- feed scene evidence later;
- not become a cheap replacement for useful answers.

## 7. Feedback Learning — ⬜

### Goal

Learn which *types of behavior* work in a specific chat without rewriting the personality after one reaction.

### Evidence model

Possible evidence strength:

- one positive reaction -> weak positive evidence;
- multiple independent reactions -> stronger evidence;
- someone quotes/reuses a Yayceslav line later -> strong evidence;
- participants continue Yayceslav’s joke -> strong evidence;
- explicit “stop repeating this” feedback -> strong negative evidence;
- repeated ignored proactive behavior -> weak negative evidence;
- explicit owner feedback -> high-confidence evidence.

### Promotion pipeline

Use a staged process:

`evidence -> candidate preference -> repeated confirmation -> promoted preference`

Example candidate:

> In this chat, short literal-flip punches outperform long pseudo-scientific metaphors.

### Safety / quality requirements

- no learning from one isolated reaction;
- bounded number of active preferences;
- confidence/decay;
- rollback support;
- no learning of sensitive personal claims as “preferences” or “facts”;
- preferences affect style/selection, not factual truth.

## 8. Episode Memory — ⬜

### Goal

Move beyond “what facts do we know about a person?” toward “what happened in this memorable shared event?”.

### Episode shape

A compact episode may contain:

- date/time window;
- participants;
- topic;
- notable statements;
- verified contradiction/self-own;
- scene/coalition information;
- resolution/disengagement;
- whether the event is useful for a future callback.

Example abstraction:

> Car argument: participant A claimed X, later denied X, participant B produced evidence, the group reacted, A ended with “I do not care”.

### Requirements

- summarize selectively, not every conversation;
- no unbounded transcript storage;
- sensitive claims remain guarded;
- callbacks must preserve uncertainty and provenance;
- old episodes decay or become less likely to surface.

## 9. Resource-budget guardrails for all future stages

The roadmap is intended to fit a small single-service Railway-style deployment.

Preferred design:

- SQLite;
- bounded dictionaries/deques;
- TTL/decay;
- existing Telegram metadata;
- existing model call enriched with better context.

Avoid by default:

- local embedding models;
- local LLMs;
- Qdrant/Chroma/vector DB;
- Redis;
- separate always-on worker services;
- LLM summaries on every message;
- extra model calls merely for turn/scene classification when deterministic evidence is enough.

If semantic embeddings become genuinely useful later, prefer an external API or explicitly reassess the hosting budget rather than silently adding a heavy local service.

## 10. Future private-repository migration — ⏸️ DEFERRED

`oblakaF/yayceslav-core` exists as a private placeholder for a possible future production repository.

**Current decision:** do not migrate yet.

Until an explicit future decision:

- development stays in public `yayceslav-bot`;
- Railway stays connected to public `main`;
- CI stays in public `yayceslav-bot`;
- `yayceslav-core` is not the source of truth;
- do not split public/private feature development.

If migration is approved later, use this order:

1. create/verify a complete private copy of the desired history or stable production baseline;
2. verify commits, branches/tags and source completeness;
3. establish private CI and branch protection;
4. move internal roadmap/experiments to the private repository;
5. switch Railway only after private CI is green;
6. verify the exact deployed commit and Telegram smoke behavior;
7. only then reduce the public repository to a curated public/source-available edition;
8. never move secrets, live SQLite data or raw private chat archives into Git merely because the repository is private.

## Execution order

The agreed implementation order is:

1. **Live Fight Test**
2. **Final Fight tuning, only if the live log exposes real issues**
3. **Fight System v1 Stable**
4. **GitHub settings / Actions-storage housekeeping**
5. **Social Scene Graph v1**
6. **Scene-aware conversation and fights**
7. **Turn Actor: REPLY / WAIT / PASS / REACT**
8. **Telegram reactions as first-class behavior**
9. **Feedback Learning**
10. **Episode Memory**
11. **Private-repository migration only after a separate future decision**

Do not reorder the major stages casually. In particular, do not start self-learning before scene understanding and turn timing are stable, because otherwise the system would learn from behavior that is still being redesigned.
