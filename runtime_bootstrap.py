"""Ordered bootstrap for V2 runtime extensions.

This module exists only to make the side-effect import chain explicit. Import
order is part of the current runtime contract because several legacy runtime
modules wrap ``Application.run_polling``. Keep additions here deliberate and
covered by bootstrap tests; do not hide them in unrelated utility modules.
"""

from __future__ import annotations

import logging
import sys

from telegram.constants import UpdateType
from telegram.ext import Application

import schema_migrations

# Loaded early by bot.py through adaptation_cache, before thinking_engine
# installs its Gemini router. Runtime guards only patch Application.run_polling
# here; they touch bot.py functions later when the application is built.
import primitive_compact_guard  # noqa: F401
import dialogue_guard_runtime  # noqa: F401
import member_profile_runtime  # noqa: F401
import member_memory_safety_patch  # noqa: F401
import dialogue_followup_mode_patch

# Monthly social still owns a legacy polling wrapper. Unified daily titles no
# longer does: bootstrap prepares unified first at polling time, then the legacy
# monthly wrapper can safely wrap that scheduler without it being overwritten.
import monthly_social_runtime  # noqa: F401
import unified_daily_title_runtime
import relationship_experience_runtime
import whoami_profile_v3_runtime
# Monthly memory scope now also owns theme quality/ranking directly.
import monthly_memory_scope_patch  # noqa: F401
import whoami_profile_v4_runtime

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
    "monthly_social_runtime",
    "unified_daily_title_runtime",
    "relationship_experience_runtime",
    "whoami_profile_v3_runtime",
    "monthly_memory_scope_patch",
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


def ensure_chat_member_updates(kwargs: dict) -> None:
    """Preserve explicit allowed_updates while ensuring member events arrive.

    If PTB is left to choose its default update set (allowed_updates is absent
    or None), keep it untouched. If the caller supplied an explicit iterable,
    append CHAT_MEMBER exactly once. This is the behavior previously provided
    by chat_member_updates_patch.py, now centralized in the bootstrap wrapper.
    """
    allowed = kwargs.get("allowed_updates")
    if allowed is None:
        return
    allowed_list = list(allowed)
    if UpdateType.CHAT_MEMBER not in allowed_list:
        allowed_list.append(UpdateType.CHAT_MEMBER)
    kwargs["allowed_updates"] = allowed_list


def prepare_polling_runtime(kwargs: dict) -> None:
    """Apply small non-schema polling preparations without extra wrappers."""
    # This used to be its own Application.run_polling wrapper. Keep the same
    # best-effort behavior: install() may return False if the bot module is not
    # ready, but that has never blocked polling.
    dialogue_followup_mode_patch.install()
    ensure_chat_member_updates(kwargs)


def prepare_application_runtime(application: Application) -> None:
    """Prepare application-owned features that no longer need polling wrappers."""
    # This must precede monthly_social_runtime's legacy wrapper execution: its
    # _patch_scheduler() captures and wraps the unified scheduler installed here.
    unified_daily_title_runtime._prepare()
    relationship_experience_runtime._prepare_application(application)
    # v3 must prepare after monthly_memory_scope_patch has installed its
    # calendar-month storage functions; import order above preserves that.
    whoami_profile_v3_runtime._prepare_application(application)
    whoami_profile_v4_runtime._prepare_application(application)


def _install_preflight_hook() -> None:
    """Make schema/runtime preparation the outermost run_polling wrapper."""
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
        prepare_application_runtime(self)
        prepare_polling_runtime(kwargs)
        return original_run_polling(self, *args, **kwargs)

    Application.run_polling = run_polling_with_schema_preflight
    Application._yayceslav_schema_preflight_installed = True


_install_preflight_hook()
