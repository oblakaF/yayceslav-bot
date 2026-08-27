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
import accountability_runtime
import positive_runtime
import reputation_runtime
import reputation_daily_runtime
import reputation_decay_runtime
import daily_mood_runtime
import member_profile_runtime
import episodic_memory_runtime
import pairwise_relationship_runtime
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
import initiative_runtime
import birthday_runtime

# Free-tier smart tools and production guards. All are explicit, bounded runtime
# layers: no readiness thread, browser, cache, vector DB, or transcript storage.
import natural_router_runtime
import search_enrichment_runtime
import chat_digest_runtime
import date_grounding_runtime
import social_priority_runtime
import conflict_rage_runtime
import search_context_runtime
import search_slang_runtime
import voice2_runtime
import recent_video_note_runtime
import sticker_tuning_runtime


# Exposed for a small contract test. This documents the critical ordering
# without inspecting source text or depending on import implementation details.
RUNTIME_LOAD_ORDER = (
    "primitive_compact_guard",
    "dialogue_guard_runtime",
    "accountability_runtime",
    "positive_runtime",
    "reputation_runtime",
    "reputation_daily_runtime",
    "reputation_decay_runtime",
    "daily_mood_runtime",
    "member_profile_runtime",
    "episodic_memory_runtime",
    "pairwise_relationship_runtime",
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
    "initiative_runtime",
    "birthday_runtime",
    "search_enrichment_runtime",
    "chat_digest_runtime",
    "natural_router_runtime",
    "date_grounding_runtime",
    "social_priority_runtime",
    "conflict_rage_runtime",
    "search_context_runtime",
    "search_slang_runtime",
    "voice2_runtime",
    "recent_video_note_runtime",
    "sticker_tuning_runtime",
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
    dialogue_followup_mode_patch.install()
    ensure_chat_member_updates(kwargs)


def _prepare_sticker_menu_runtime(application: Application) -> None:
    """Prepare the sticker/menu startup layer without polling wrappers."""
    # Tuning wraps the Aug19 semantic install hook, so it must attach before
    # install_runtime_behavior is called and before Telegram sticker handlers
    # capture own_pack_sticker_listener.
    sticker_tuning_runtime.install()

    # Lazy imports are intentional. bot.py imports adaptation_cache (and thus
    # this bootstrap) before the sticker/menu modules; importing them here at
    # polling startup avoids changing bot.py import order or creating cycles.
    import praise_guard_runtime
    import sticker_semantics_aug19

    sticker_semantics_aug19.install_catalog_semantics()

    import scoped_help_runtime
    import sticker_post_runtime
    import sticker_runtime

    praise_guard_runtime.install()
    sticker_semantics_aug19.install_runtime_behavior()

    sticker_runtime.prepare_application_runtime(application)
    scoped_help_runtime.prepare_application_runtime(application)
    sticker_post_runtime.install_send_answer_wrapper()

    logging.warning(
        "Yayceslav stickers runtime ready: registry=%s; own-pack=50%% semantic sticker/text; "
        "foreign packs ignored; tuned probabilities with shared cap=%s/hour",
        len(sticker_runtime.sticker_engine.STICKER_ORDER),
        sticker_runtime.STICKER_MAX_PER_WINDOW,
    )
    logging.warning("Scoped /help runtime ready: group/private/owner")


def prepare_application_runtime(application: Application) -> None:
    """Prepare application-owned features from one explicit startup path."""
    _prepare_sticker_menu_runtime(application)
    unified_daily_title_runtime._prepare()
    monthly_social_runtime._prepare_application(application)
    relationship_experience_runtime._prepare_application(application)
    member_profile_runtime._prepare_application(application)
    episodic_memory_runtime._prepare_application(application)
    pairwise_relationship_runtime._prepare_application(application)
    whoami_profile_v3_runtime._prepare_application(application)
    whoami_profile_v4_runtime._prepare_application(application)

    # Compose conversational wrappers first. Voice 2.0 is installed later so
    # non-voice requests delegate through this final Gemini stack.
    dialogue_guard_runtime._prepare()
    accountability_runtime.install()
    positive_runtime._prepare_application(application)
    reputation_runtime._prepare_application(application)
    reputation_daily_runtime._prepare_application(application)
    reputation_decay_runtime._prepare()
    daily_mood_runtime._prepare_application(application)

    import rate_limit_tlen_runtime
    rate_limit_tlen_runtime.install()
    daily_content_runtime._prepare_application(application)
    initiative_runtime._prepare_application(application)
    birthday_runtime._prepare_application(application)

    # Current-date grounding is deliberately late: it wraps the fully composed
    # instruction builder, making process date/time authoritative at the edge.
    if not date_grounding_runtime.install():
        logging.warning("Date grounding runtime: bot module not ready")

    # Relationship priority is the final persistent social arbiter. Conflict
    # rage is installed one layer later: it may temporarily set a minimum
    # intensity during an active fight, but never changes long-term reputation.
    if not social_priority_runtime.install():
        logging.warning("Social priority runtime: bot module not ready")
    if not conflict_rage_runtime.install():
        logging.warning("Conflict rage runtime: bot module not ready")

    # Voice 2.0 captures the completed ask_gemini stack. The conflict runtime
    # has already attached its post-hook to the structured voice decision, so
    # addressed voice/video notes share the same short-lived hostility heat.
    if not voice2_runtime.install():
        logging.warning("Voice 2.0 runtime: bot module not ready")

    # Search 2.0 remains bounded. Context recovery wraps perform_web_search only
    # after enrichment is installed, preserving the existing search pipeline.
    search_enrichment_runtime.install()
    if not search_context_runtime.install():
        logging.warning("Search context runtime: bot module not ready")
    if not search_slang_runtime.install():
        logging.warning("Search slang runtime: bot module not ready")
    chat_digest_runtime.prepare_application_runtime(application)
    natural_router_runtime.prepare_application_runtime(application)
    recent_video_note_runtime.prepare_application_runtime(application)


def _install_preflight_hook() -> None:
    """Install the single application polling wrapper owned by the bootstrap."""
    if getattr(Application, "_yayceslav_schema_preflight_installed", False):
        return

    original_run_polling = Application.run_polling

    def run_polling_with_schema_preflight(self, *args, **kwargs):
        try:
            run_schema_preflight()
        except Exception:
            logging.exception("Schema migration preflight failed; polling not started")
            raise
        prepare_application_runtime(self)
        prepare_polling_runtime(kwargs)
        return original_run_polling(self, *args, **kwargs)

    Application.run_polling = run_polling_with_schema_preflight
    Application._yayceslav_schema_preflight_installed = True


_install_preflight_hook()

# No runtime effect: this comment exists only to retrigger Railway's GitHub autodeploy webhook.
# Second no-runtime-effect retrigger after toggling Railway Auto Deploy off/on.
# Third no-runtime-effect retrigger after Railway peak hours ended.
