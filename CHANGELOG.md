# Changelog

Notable public changes to Yayceslav are documented here. Internal experiments and private production configuration are intentionally excluded.

## 2026-08-30

### Public repository

- Added a source-available proprietary license and explicit copyright/branding notices for Vadim Krysko.
- Added public architecture, deployment and roadmap documentation.
- Clarified that the public repository is not required to mirror private production configuration or unreleased work.

### Conversation quality

- Stabilized the conflict/fight ownership chain around a single conflict FSM.
- Added bounded fight-aware sticker pacing and delayed-punch guards.
- Added sequence regression coverage for reconciliation and serious-topic cancellation.
- Added grounded post-fight callbacks using target-authored fight text.
- Added contextual roast planning with anti-repeat behavior.
- Added deterministic cross-message contradiction and self-own targeting without an additional Gemini call.

### Delivery

- CI now validates the production branch on Python 3.12 and 3.13.
- Railway deployment tracking was aligned with `main` so a deployed commit can be matched to the tested production revision.

## Earlier development

The repository's Git and pull-request history contains the detailed development record for earlier iterations, including social memory, voice, search, stickers, relationship behavior and V2 architecture work.
