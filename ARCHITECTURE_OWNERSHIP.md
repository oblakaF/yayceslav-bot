# Yayceslav production architecture ownership

This document is a guardrail against solving the same problem twice in parallel runtimes.
It describes **production ownership**, not every historical file that remains in the repository.

## Rules

1. Every stateful concern has one production owner.
2. A wrapper may enrich an owner's input/output, but must not create a second copy of its state machine.
3. Historical rollback modules are not production modules merely because their files still exist.
4. New fixes should modify the existing owner or an explicitly documented extension point before adding another runtime.
5. `runtime_bootstrap.py` is the source of truth for production installation order.

## Ownership map

| Concern | Production owner | Supporting layers | Legacy / historical boundary |
| --- | --- | --- | --- |
| Conflict phase/state | `conflict_fsm_runtime.py` | `social_priority_runtime.py`, `title_conflict_runtime.py` | `conflict_rage_runtime.py`, `rage_hotfix_runtime.py` are rollback/history and must not be installed |
| Fight turn routing | `fight_routing_v3.py` | `fight_routing_v3_patterns.py`, `primitive_compact_guard.py` | older fight/rage branch implementations are history once merged |
| RAGE punch planning | `roast_engine.py` | `roast_engine_runtime.py`, `roast_lexicon.py` | do not add another RAGE state owner or second Gemini call |
| Claim-sensitive memory | `claim_memory_v3.py` | monthly/short-term memory recorders | sensitive bait must remain a claim, not biography |
| Voice/media response | `voice2_runtime.py` | `recent_video_note_runtime.py` | older voice behavior must not independently capture/replace the final Gemini stack |
| Search context | `search_enrichment_runtime.py` | `search_context_runtime.py`, `search_slang_runtime.py`, `lexical_search_v3.py`, `evidence_grounding_runtime.py` | new lexical/search hotfixes should extend this chain, not create a parallel search router |
| Stickers | `sticker_runtime.py` / `sticker_engine.py` | `sticker_tuning_runtime.py`, `sticker_post_runtime.py`, `sticker_semantics_aug19.py` | sticker asset-preparation branches/tools are not production runtime owners |
| Social baseline | `social_priority_runtime.py` | reputation/member/relationship runtimes | temporary conflict belongs to conflict FSM, not relationship state |
| Application startup | `runtime_bootstrap.py` | explicit `prepare_application_runtime` calls | no feature should add a competing `Application.run_polling` owner |

## Conflict / fight request path

`social relationship baseline -> conflict_fsm_runtime -> voice/search enrichment -> fight_routing_v3 -> roast_engine_runtime`

The responsibilities are deliberately different:

- `conflict_fsm_runtime`: decides and stores NORMAL/WARNING/RAGE.
- `fight_routing_v3`: isolates the current turn, applies compact fight/conversation routing, and owns the one-shot post-fight afterburner.
- `roast_engine_runtime`: when the FSM is already in RAGE, supplies a rotating contextual attack angle to the existing Gemini request. It does not own conflict state and does not make a second model request.

## Known cleanup debt

### Fight regex split

`fight_routing_v3_patterns.py` mutates regex objects in `fight_routing_v3` at import time. This is intentional historical hotfix behavior but obscures the effective production pattern set. Future cleanup should move the complete pattern catalog to one declarative module and have both routing and tests import it without monkey-patching.

### Historical conflict modules

`conflict_rage_runtime.py` and `rage_hotfix_runtime.py` remain useful for history/rollback but must stay outside `RUNTIME_LOAD_ORDER` and production preparation. Their presence on disk is not evidence that they should be edited for a new fight bug.

### Diverged historical branches

A branch with commits not in `main` is not automatically missing production functionality. Before cherry-picking or merging it, compare its behavior against the current owner above. In particular, old conflict/search/voice fixes may have been superseded by later architecture even when their exact commits were never merged.

## Change checklist

Before adding a runtime or hotfix:

- Identify the concern in this ownership map.
- Inspect the current owner and bootstrap order.
- Search for an existing extension/helper before creating a new file.
- Confirm the change does not add a second state owner, polling hook, model call, or duplicate recorder.
- Add a test at the ownership boundary.
- Update this document if responsibility genuinely changes.
