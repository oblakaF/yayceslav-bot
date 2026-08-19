"""Ordered bootstrap for V2 runtime extensions.

This module exists only to make the side-effect import chain explicit. Import
order is part of the current runtime contract because several legacy runtime
modules wrap ``Application.run_polling``. Keep additions here deliberate and
covered by bootstrap tests; do not hide them in unrelated utility modules.
"""

from __future__ import annotations

import logging
import sys

from telegram.ext import Application

import schema_migrations

# Loaded early by bot.py through adaptation_cache, before thinking_engine
# installs its Gemini router. Runtime guards only patch Application.run_polling
# here; they touch bot.py functions later when the application is built.
import primitive_compact_guard  # noqa: F401
import dialogue_guard_runtime  # noqa: F401
import member_profile_runtime  # noqa: F401
import member_memory_safety_patch  # noqa: F401
import dialogue_followup_mode_patch  # noqa: F401
import chat_member_updates_patch  # noqa: F401

# Monthly report must be imported BEFORE unified daily titles. Because each
# runtime wraps Application.run_polling, this order ensures unified titles are
# installed first at startup and the monthly report then wraps that final
# scheduler instead of being overwritten.
import monthly_social_runtime  # noqa: F401
import monthly_report_timing_patch  # noqa: F401
import unified_daily_title_runtime  # noqa: F401
import relationship_experience_runtime  # noqa: F401
import whoami_profile_v3_runtime  # noqa: F401
import monthly_memory_scope_patch  # noqa: F401
import monthly_theme_quality_patch  # noqa: F401
import whoami_profile_v4_runtime  # noqa: F401

# External daily content wraps the already assembled title/month scheduler.
import daily_content_runtime  # noqa: F401
import daily_content_source_patch  # noqa: F401


# Exposed for a small contract test. This documents the critical ordering
# without inspecting source text or depending on import implementation details.
RUNTIME_LOAD_ORDER = (
    "primitive_compact_guard",
    "dialogue_guard_runtime",
    "member_profile_runtime",
    "member_memory_safety_patch",
    "dialogue_followup_mode_patch",
    "chat_member_updates_patch",
    "monthly_social_runtime",
    "monthly_report_timing_patch",
    "unified_daily_title_runtime",
    "relationship_experience_runtime",
    "whoami_profile_v3_runtime",
    "monthly_memory_scope_patch",
    "monthly_theme_quality_patch",
    "whoami_profile_v4_runtime",
    "daily_content_runtime",
    "daily_content_source_patch",
)


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "get_db_connection", None)):
            return module
    return None


def run_schema_preflight() -> tuple[int, ...]:
    """Apply pending schema migrations immediately before polling starts."""
    bot_module = _find_bot_module()
    if bot_module is None:
        raise RuntimeError("Bot DB module is not ready for schema migration preflight")
    applied = schema_migrations.run_pending(bot_module)
    if applied:
        logging.warning("Schema migrations applied at startup: %s", applied)
    return applied


def _install_preflight_hook() -> None:
    """Make the migration preflight the outermost run_polling wrapper."""
    if getattr(Application, "_yayceslav_schema_preflight_installed", False):
        return

    original_run_polling = Application.run_polling

    def run_polling_with_schema_preflight(self, *args, **kwargs):
        try:
            run_schema_preflight()
        except Exception:
            # Fail closed: never start the bot against a schema whose migration
            # state is unknown or partially applied.
            logging.exception("Schema migration preflight failed; polling not started")
            raise
        return original_run_polling(self, *args, **kwargs)

    Application.run_polling = run_polling_with_schema_preflight
    Application._yayceslav_schema_preflight_installed = True


_install_preflight_hook()
