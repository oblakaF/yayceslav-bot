# Security Policy

## Supported code

Security fixes are considered for the current public `main` branch. Private production deployments may contain additional configuration or unreleased changes that are not represented here.

## Reporting a vulnerability

Please do **not** publish API keys, Telegram tokens, private chat data, database contents, user identifiers, or exploit details in a public issue.

If you believe you found a security issue in Yayceslav:

1. contact Vadim Krysko through the GitHub account associated with this repository;
2. describe the affected component and the minimum steps needed to reproduce the problem;
3. redact secrets and personal data;
4. allow reasonable time for investigation before public disclosure.

If a GitHub private vulnerability-reporting channel is enabled for the repository in the future, prefer that channel.

## Secrets

The repository must never contain real values for:

- `TELEGRAM_BOT_TOKEN`;
- `GEMINI_API_KEY`;
- hosting-provider credentials;
- production SQLite databases or chat exports containing private user data.

Use environment variables or the hosting provider's secret store. `.env`, database files, WAL files and the `data/` directory are excluded through `.gitignore`.

## Data handling

Yayceslav uses persistent social/profile state and bounded conversational memory. Operators are responsible for complying with Telegram rules and applicable privacy/data-protection requirements for the groups in which they run their instance.
