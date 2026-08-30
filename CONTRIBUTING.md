# Contributing

Yayceslav is a personal project owned and maintained by **Vadim Krysko**.

The repository is source-available under its proprietary `LICENSE`; it is not an open-source project.

## Issues

Bug reports and thoughtful technical feedback are welcome. Please:

- describe the observed behavior and expected behavior;
- provide a minimal reproducible example when possible;
- remove API keys, tokens, private chat contents and personal data;
- avoid posting production databases or private Telegram exports.

## Pull requests

External pull requests are **not accepted by default**. Open an issue or contact the owner before preparing a substantial contribution.

An unsolicited pull request does not change the repository license, transfer ownership of the project, or imply that the contribution will be merged.

If external contributions become a regular part of the project, a separate contributor agreement or contribution-license policy may be introduced before accepting substantial third-party code.

## Development rules

For invited changes:

1. branch from current `main`;
2. keep one clear concern per pull request;
3. do not add secrets or private production data;
4. preserve the single-owner architecture for stateful concerns;
5. run the full pytest suite;
6. keep behavior changes covered by regression tests;
7. do not introduce another model call or background service without a demonstrated need.

See `docs/architecture.md` for the current architecture boundaries.
