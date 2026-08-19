"""Ordered bootstrap for V2 runtime extensions.

This module makes the side-effect import chain and startup order explicit.
``Application.run_polling`` ownership is centralized here; feature runtimes
prepare through explicit functions instead of stacking polling wrappers.
Keep additions deliberate and covered by bootstrap behavior tests.
"""

from __future__ import annotations

import logging
import sys

from telegram.constants import UpdateType
from telegram.ext import Application

import schema_migrations

# Loaded early by bot.py through adaptation_cache, before thinking_engine
# installs its Gemini router. Runtime helpers can patch bot.py functions later
# when the application is built, but polling ownership stays centralized below.
import primitive_compact_guard  # noqa: F401
import dialogue_guard_runtime
import member_profile_runtime
import member_memory_safety_patch  # noqa: F401
import dialogue_followup_mode_patch

# Unified daily titles must prepare before monthly social: monthly captures and
# wraps the unified scheduler so both daily titles and the 19:00/catch-up report
# stay on the same scheduler path without either runtime wrapping run_polling.
import monthly_social_runtime
import unified_daily_title_runtime
import relationship_experience_runtime
import whoami_profile_v3_runtime
# Monthly memory scope now also owns theme quality/ranking directly.
import monthly_memory_scope_patch  # noqa: F401
import whoami_profile_v4_runtime

# External daily-content source selection remains an import-time patch, but its
# runtime scheduler preparation is centralized here like the other safe layers.
import daily_content_runtime
import daily_content_source_patch  # noqa: F401


# These class sentinels are the compatibility contract used by three older
# sticker/menu modules. Bootstrap claims them before those modules are imported
# later by bot.py, so their legacy run_polling hooks become no-ops. Their actual
# preparation functions are called explicitly from prepare_application_runtime.
LEGACY_POLLING_SENTINELS = (
    "_yayceslav_sticker_patch_installed",
    "_yayceslav_scoped_help_patch_installed",
    "_yayceslav_post_sticker_runtime_installed",
)


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


def _prepare_sticker_menu_runtime(application: Application) -> None:
    """Prepare the old sticker/menu startup layer without polling wrappers."""
    # Lazy imports are intentional. bot.py imports adaptation_cache (and thus
    # this bootstrap) before the sticker/menu modules; importing them here at
    # polling startup avoids changing bot.py import order or creating cycles.
    import scoped_help_runtime
    import sticker_post_runtime
    import sticker_runtime

    # Preserve the old wrapper execution order:
    # sticker runtime -> scoped help -> post-answer send wrapper -> bootstrap.
    sticker_runtime.prepare_application_runtime(application)
    scoped_help_runtime.prepare_application_runtime(application)
    sticker_post_runtime.install_send_answer_wrapper()

    logging.warning(
        "Yayceslav stickers runtime ready: pack=%s; own-pack=50%% semantic sticker/text; "
        "foreign packs ignored; question<=5%% semantic-only; background<=2%%; "
        "background cap=%s/hour",
        len(sticker_runtime.sticker_engine.STICKER_ORDER),
        sticker_runtime.STICKER_MAX_PER_WINDOW,
    )
    logging.warning("Scoped /help runtime ready: group/private/owner")


def prepare_application_runtime(application: Application) -> None:
    """Prepare application-owned features from one explicit startup path."""
    _prepare_sticker_menu_runtime(application)
    # Order is a runtime contract: monthly captures the unified scheduler and
    # appends its report after the daily-title run.
    unified_daily_title_runtime._prepare()
    monthly_social_runtime._prepare_application(application)
    # Relationship must wrap the base profile before member-profile memory
    # augmentation wraps that enriched profile. Safety/monthly-memory patches
    # are already installed by the import chain above before this runs.
    relationship_experience_runtime._prepare_application(application)
    member_profile_runtime._prepare_application(application)
    # v3 must prepare after monthly_memory_scope_patch has installed its
    # calendar-month storage functions; import order above preserves that.
    whoami_profile_v3_runtime._prepare_application(application)
    whoami_profile_v4_runtime._prepare_application(application)
    # Dialogue guard patches bot-level Gemini/instruction/rate-limit functions;
    # keep it after the application-owned feature preparation as before.
    dialogue_guard_runtime._prepare()
    # Daily content captures the already-composed daily+monthly scheduler and
    # appends its own due checks; source-network logic is untouched.
    daily_content_runtime._prepare_application(application)


def _claim_legacy_polling_ownership() -> None:
    """Make later legacy sticker/menu hook installers harmless."""
    for attribute in LEGACY_POLLING_SENTINELS:
        setattr(Application, attribute, True)


def _install_preflight_hook() -> None:
    """Install the single application polling wrapper owned by the bootstrap."""
    _claim_legacy_polling_ownership()
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
