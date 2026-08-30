# Deployment

Yayceslav is designed to run as a single Python service with SQLite persistence.

The public repository contains no production tokens, private chat database, or Railway account configuration.

## Requirements

- Python 3.12 or 3.13
- Telegram bot token
- Gemini API key
- persistent writable storage for SQLite if you want state to survive restarts

## Environment variables

Required:

```text
TELEGRAM_BOT_TOKEN=...
GEMINI_API_KEY=...
```

Optional:

```text
BOT_OWNER_ID=...
```

Keep secrets in your hosting provider's secret/variable store or a local `.env` file. Never commit real values.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate       # Windows

python -m pip install -r requirements.txt
python bot.py
```

## SQLite persistence

Locally the database is stored under `data/`.

On the current Railway-style deployment, the application automatically uses `/app/data` when that directory exists. Mount persistent storage there if you want reputation, settings, profiles and other persistent state to survive container replacement.

Database schema changes are handled through non-destructive startup migrations. Existing tables are created with `CREATE TABLE IF NOT EXISTS` and compatible columns are added through migration helpers.

## Telegram privacy mode

A group bot only sees the updates Telegram sends to it. If Telegram Privacy Mode is enabled, ordinary group conversation may be invisible to the bot, which makes group statistics, background social context and proactive behavior incomplete.

If your use case requires observing normal group messages, configure Privacy Mode appropriately in BotFather and follow Telegram's current bot/privacy documentation.

## CI and release path

The public repository uses GitHub Actions on pull requests and on pushes to `main`, testing Python 3.12 and 3.13.

The production deployment is intentionally separate from repository documentation. A typical release path is:

```text
feature branch -> pull request -> CI -> merge to main -> production deployment
```

Do not assume that a successful build proves Telegram behavior; important social changes should also receive a live smoke test.

## Production/private divergence

A live deployment may use private configuration or newer unreleased code. The public source-available repository is not a guarantee that every production detail, dataset, private prompt, operational note or future experiment is published.
