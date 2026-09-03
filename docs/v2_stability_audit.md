# Yayceslav v2 Stability & Acceptance Audit

Date: 2026-09-03
Scope: current `main` after the v2 personality/memory/recommendation/self-development roadmap and the live direct-ping sticker fix.

## Result

**Status: stable candidate, with one acceptance defect found and fixed in this audit.**

The audit did not add a new product vertical. It hardened the contracts already promised by Roadmap v2 and converted the most important architecture assumptions into CI tests.

## Defect found: cross-category generic recommendation follow-up

### Symptom

All recommendation verticals kept independent short-lived topic state. Those states can coexist in the same group chat. A category-less follow-up such as `а ещё?` was therefore ambiguous when, for example, a game request was followed by a movie request within the two-hour TTL.

Because Telegram handlers have fixed group priorities, the earlier handler could capture the generic follow-up even when its topic was older. This violated acceptance criterion 13: category-local follow-ups must not cross-contaminate music/books/films/games.

Music was especially vulnerable because its follow-up used the generic entity-continuity topic rather than a music-only topic.

### Fix

`recommendation_followup_guard_runtime.py` adds one bounded chat-local pointer to the latest explicit recommendation category.

- category-less `а ещё? / что ещё? / дай ещё / а похожее` is accepted only by the active category;
- explicit/category-named follow-ups such as `ещё игры` are not blocked and can intentionally switch category;
- owner state expires after two hours and is capped at 256 chats;
- no database table, provider call, Gemini call or polling wrapper is added;
- existing provider/ranking runtimes remain unchanged.

Regression tests reproduce the exact stale-game/newer-movie collision and verify that the movie owns the generic follow-up while the old game seed can still be addressed explicitly.

## Acceptance review

| # | Roadmap contract | Audit status |
|---|---|---|
| 1 | Durable reasoned self-choice | Covered by self-canon/imagination tests |
| 2 | Later identity continuity | Covered by persistent self-canon storage/injection tests |
| 3 | Explicit justified identity revision | Covered by self-canon v2 inertia guard tests |
| 4 | Stable personal music taste | Covered by self-canon + music lens separation |
| 5 | Music metadata specialist grounding | Existing MusicBrainz runtime/tests |
| 6 | Lyrics provider path independent of catalog success | Existing lyrics bridge tests |
| 7 | ListenBrainz recommendation candidates | Existing music recommendation tests |
| 8 | Chat/member isolation | Existing chat-local canon, topic and relationship tests; follow-up owner is also chat-local |
| 9 | Reconciliation beats stale conflict | Existing relationship/conflict regression tests |
| 10 | Open Library recommendations | Existing book recommendation tests |
| 11 | TMDB recommendations when configured | Existing movie tests; missing token fails open |
| 12 | RAWG recommendations when configured | Existing game tests; missing key fails open |
| 13 | Category-local `а ещё?` | **Defect found and fixed in this audit** |
| 14 | Recommendation never silently mutates self-canon | Provider-neutral identity contract retained |
| 15 | Rare development requires durable history + explanation | Existing self-development tests |
| 16 | High-inertia identity cannot be autonomously rewritten | Parser allowlist + new acceptance-contract test |

## Architecture hardening checks added to CI

`tests/test_v2_acceptance_contract.py` now protects these invariants:

- travel/places remains removed from Roadmap v2;
- `Application.run_polling` ownership remains centralized in `runtime_bootstrap.py`;
- recommendation/self-development runtimes do not introduce polling wrappers;
- music/books/movies/games are all registered through bootstrap patches;
- specialist handler groups remain distinct;
- TMDB/RAWG missing credentials fail open to the normal bot route;
- persistent semantic memory installs before rare self-development and multimodal remains outermost;
- autonomous development cannot touch high-inertia identity;
- generic recommendation follow-up ownership stays bounded and expiring.

## Live-only checks that CI cannot prove

The following still require ordinary production observation rather than synthetic unit tests:

1. Telegram/network latency under Railway load and external provider response time.
2. Actual current catalog quality returned by TMDB, RAWG, ListenBrainz and Open Library.
3. Seven-day natural self-development behavior with real accumulated group history.
4. Subjective conversational quality of long mixed-mode sessions (text/voice/photo/video-note) despite structural continuity tests.

These are operational/product observations, not known code defects from this audit.

## Release assessment

If the full Python 3.12/3.13 CI matrix passes with the new regression tests, the audited branch is suitable to mark as **Yayceslav v2 stable candidate**. Future feature work should start from a v3 roadmap rather than extending v2 opportunistically.
