import bot
import runtime_config
import sticker_runtime
import thinking_engine


def test_runtime_data_paths_cannot_silently_diverge():
    assert bot.DATA_DIR == runtime_config.DATA_DIR
    assert bot.STATS_DB_PATH == runtime_config.STATS_DB_PATH
    assert sticker_runtime.STICKER_ID_CACHE_PATH == runtime_config.STICKER_ID_CACHE_PATH
    assert thinking_engine._STATE_FILE == runtime_config.GEMINI_ROUTER_STATE_PATH
