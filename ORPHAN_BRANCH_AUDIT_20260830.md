# Orphan branch audit — 2026-08-30

Base checked: `main` at `9bd980df44e654c91eb235ecd405e1f9e1cb68c8`.

Purpose: verify that old feature/fix/audit branches do not contain useful production behavior missing from the production branch. A branch having unique commits does **not** automatically mean that behavior is missing: many old commits were later reimplemented, merged through another branch, or superseded by a newer owner.

## Result

58 repository branches were enumerated and compared against `main`.

### Production history already contained in `main` (`ahead_by = 0`)

These branches are ancestors of current production. They contain no unique commit that needs recovery:

- `agent/daily-title-scheduler-status`
- `audit/architecture-cleanup-20260829`
- `cleanup/fight-pattern-source-of-truth`
- `feature/chat-adaptation-v2`
- `feature/conflict-rage-roast-fix`
- `feature/explicit-voice-reply-fix`
- `feature/fight-memory-afterburner-v2`
- `feature/free-tier-smart-tools`
- `feature/fsm-rage-grounded-media`
- `feature/hard-rage-latch`
- `feature/hide-naturalized-slash-commands`
- `feature/human-yayceslav`
- `feature/human-yayceslav-v2-audit-architecture`
- `feature/human-yayceslav-v2-audit-fixes`
- `feature/human-yayceslav-v2-audit-safe`
- `feature/human-yayceslav-v2`
- `feature/rage-answer-and-sting`
- `feature/rage-consistency-punches`
- `feature/rage-counterattack`
- `feature/rage-detection-and-compact`
- `feature/rage-pacing-double-punch-stickers`
- `feature/recent-video-note-followup`
- `feature/reliability-decay-jokes`
- `feature/runtime-hotfix-cleanup`
- `feature/search-accountability-don-parody`
- `feature/search-proof-routing`
- `feature/search-slang-proof`
- `feature/self-roast-natural-language`
- `feature/semantic-monthly-themes`
- `feature/social-priority-unified-tone`
- `feature/social-priority-video-context`
- `feature/video-note-vision-memory-fix`
- `feature/voice2-sticker-tuning`
- `feature/whoami-sympathy-themes`
- `feature/whoami-true-monthly-status`
- `feature/yayceslav-new-sticker-semantics`
- `fight-mode-v2`
- `fight-routing-v3`
- `fix/hostile-compact-old-russian-weight`
- `fix/human-simple-hostile-replies`
- `fix/human-verdict-taunt-rhythm`
- `fix/v2-bare-followup-no-search`
- `fix/v2-dynamic-thinking-latency`
- `hotfix/voice-date-search-guard-20260825`
- `roast-engine-v1`
- `test/rage-transcript-regression`
- `vim-birger-calc-20260725`

`main` itself is the production head and is not an orphan.

### Diverged branches with unique commits — audited

#### `feature/owner-social-diagnostics` — **recover**

Unique behavior: owner-only `/social_debug`, a read-only view of the exact relationship band inputs already used by `social_priority_runtime`.

Decision: useful and still compatible. Reimplemented on current `main` instead of merging the old branch. The recovered runtime reads current profile/reputation/affinity state, exposes no raw callback-memory terms, creates no storage and makes no model call.

#### `fix/conflict-detection-lazy-gate` — **partial semantic recovery, do not merge**

Unique tree delta: old `humanizer_engine.py`, tests, and an older `thinking_engine.py`.

- The old thinking/model fallback is superseded by current `thinking_engine.py`, which has richer current-turn extraction and persistent 3.6 -> 3.1 routing/cooldown behavior.
- The old humanizer monkey-patched `personality.HOSTILE_RE`; reviving that would violate the current single-owner conflict architecture.
- A useful subset of direct/ambiguous insult recognition was genuinely absent from the later FSM chain. Those lexical cases are recovered declaratively in `fight_patterns.EXTRA_FIGHT_RE`, which is already the documented extension consumed by `fight_routing_v3` after the conflict FSM is installed.

Decision: recover only the missing language coverage, not the obsolete monkey-patch/state design.

#### `agent/add-gemini-version-command` — **semantically absorbed**

Unique commits are from an early branch, but current `main` already has the owner-only `/geminiversion` handler and Gemini 3.6 configuration. No recovery needed.

#### `agent/human-gemini-3-6-version` — **semantically absorbed**

Early Gemini 3.6 + `/geminiversion` integration. Current `main` contains the same feature plus the later dynamic thinking/router stack. No recovery needed.

#### `agent/update-gemini-3-6-flash` — **semantically absorbed**

Early model switch. Current `main` uses `gemini-3.6-flash`. No recovery needed.

#### `audit/free-serverless-20260816` — **audit/history only**

Unique commits produce no production tree delta that should be reintroduced. Keep as historical audit branch.

#### `fix/hostile-brevity-reaction-feedback` — **stale test-only branch**

Its unique file is a historical hostile-output test with an expectation that later hot turns may stop being physically compacted. Current conflict/Fight Routing behavior deliberately evolved after that point. No production recovery needed.

#### `feature/rage-quality-v2-regression` — **test variant superseded**

One unique test-file variant remains, but current `main` contains the same transcript regression with the later semantic safety assertion. No production recovery needed.

#### `feature/stickers` — **developer tooling, not production runtime**

Unique files are sticker preparation tooling (`stickers/README.md`, `prepare_sticker.py`, requirements and source/output scaffolding). They do not alter the live bot. Keep the branch as an asset-preparation toolbox; do not make it a production runtime dependency.

#### `test/free-serverless-audit-20260816` — **historical CI/test tooling**

Unique content is an old audit workflow and restart tests for the pre-consolidation startup model. Current production startup is owned by `runtime_bootstrap.py`; blindly restoring the old workflow/tests would encode outdated scheduler assumptions. No production recovery needed.

## Production invariants after recovery

- `main` remains the only Railway production source branch.
- `runtime_bootstrap.py` remains the single application startup owner.
- `conflict_fsm_runtime.py` remains the only conflict phase/state owner.
- `fight_patterns.py` is declarative language coverage only; it owns no state and makes no calls.
- `owner_social_diagnostics_runtime.py` is read-only and does not alter relationship state.
- Old `humanizer/personality` conflict monkey-patches are not revived.
- No extra Gemini call, DB table, worker or polling owner is introduced by this recovery.

## Remaining branches

No other branch among the 58 checked contains a unique production behavior that should be merged into the current architecture. Old branches may remain for history/rollback until a separate branch-cleanup operation is requested; deleting them is intentionally outside this audit.
