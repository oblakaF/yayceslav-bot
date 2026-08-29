import os
import sys
from pathlib import Path

import pytest


os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _clear_mapping_if_loaded(module_name: str, *attribute_names: str) -> None:
    module = sys.modules.get(module_name)
    if module is None:
        return
    for name in attribute_names:
        value = getattr(module, name, None)
        clear = getattr(value, "clear", None)
        if callable(clear):
            clear()


def _reset_loaded_runtime_state() -> None:
    """Reset only modules tests have already imported.

    This deliberately does not import the bot or runtime modules itself: the
    fixture must isolate tests without changing import order or bootstrapping
    modules that a test never needed.
    """
    _clear_mapping_if_loaded(
        "bot",
        "GROUP_MEMORY",
        "PRIVATE_MEMORY",
        "REQUEST_TIMES",
        "LAST_LIMIT_WARNING",
        "STORY_STATE",
    )
    _clear_mapping_if_loaded("style_engine", "_LENGTH_HISTORY")
    _clear_mapping_if_loaded("humor_engine", "REPETITION_TRACKER")
    _clear_mapping_if_loaded(
        "sticker_runtime",
        "_CHAT_LAST_STICKER",
        "_USER_LAST_STICKER",
        "_CHAT_STICKER_TIMES",
        "_OWNER_GROUP_MENU_INSTALLED",
    )

    state_engine = sys.modules.get("state_engine")
    reset_state = getattr(state_engine, "reset_state", None) if state_engine else None
    if callable(reset_state):
        reset_state()

    cache = sys.modules.get("adaptation_cache")
    clear_cache = getattr(cache, "clear", None) if cache else None
    if callable(clear_cache):
        clear_cache()


@pytest.fixture(autouse=True)
def isolate_loaded_runtime_state():
    _reset_loaded_runtime_state()
    yield
    _reset_loaded_runtime_state()
