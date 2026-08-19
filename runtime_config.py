"""Shared low-level runtime paths.

Keep filesystem location rules here for satellite modules. The legacy bot.py
still exposes DATA_DIR/STATS_DB_PATH for compatibility; tests assert that its
values stay identical until bot.py is split and can import this module directly.
"""

from __future__ import annotations

from pathlib import Path


RAILWAY_DATA_DIR = Path("/app/data")
DATA_DIR = RAILWAY_DATA_DIR if RAILWAY_DATA_DIR.exists() else Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATS_DB_PATH = DATA_DIR / "yayceslav_stats.db"
STICKER_ID_CACHE_PATH = DATA_DIR / "yayceslav_sticker_ids.json"
GEMINI_ROUTER_STATE_PATH = DATA_DIR / "gemini_model_router.json"
