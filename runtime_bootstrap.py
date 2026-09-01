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

import monthly_social_runtime
import unified_daily_title_runtime
import title_reroll_runtime
import relationship_experience_runtime
import whoami_profile_v3_runtime
import monthly_memory_scope_patch  # noqa: F401
import claim_memory_v3
import whoami_profile_v4_runtime

import daily_content_runtime
import daily_content_source_patch  # noqa: F401
import initiative_runtime
import birthday_runtime

import natural_router_runtime
import roast_target_runtime
import search_enrichment_runtime
import chat_digest_runtime
import date_grounding_runtime
import social_priority_runtime
import social_grounding_runtime
import owner_social_diagnostics_runtime
import conflict_fsm_runtime
import title_conflict_runtime
import search_context_runtime
import search_slang_runtime
import lexical_search_v3
import evidence_grounding_runtime
import voice2_runtime
import recent_video_note_runtime
import sticker_tuning_runtime
import fight_routing_v3
import fight_memory_afterburner_v2
import rage_pacing_runtime
import roast_engine_runtime
import shared_banter_runtime
import live_chat_regression_runtime


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
    "title_reroll_runtime",
    "relationship_experience_runtime",
    "whoami_profile_v3_runtime",
    "monthly_memory_scope_patch",
    "claim_memory_v3",
    "whoami_profile_v4_runtime",
    "daily_content_runtime",
    "daily_content_source_patch",
    "initiative_runtime",
    "birthday_runtime",
    "search_enrichment_runtime",
    "chat_digest_runtime",
    "natural_router_runtime",
    "roast_target_runtime",
    "date_grounding_runtime",
    "social_priority_runtime",
    "owner_social_diagnostics_runtime",
    "conflict_fsm_runtime",
    "social_grounding_runtime",
    "title_conflict_runtime",
    "search_context_runtime",
    "search_slang_runtime",
    "lexical_search_v3",
    "evidence_grounding_runtime",
    "voice2_runtime",
    "recent_video_note_runtime",
    "sticker_tuning_runtime",
    "fight_routing_v3",
    "fight_memory_afterburner_v2",
    "rage_pacing_runtime",
    "roast_engine_runtime",
    "shared_banter_runtime",
    "live_chat_regression_runtime",
)


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "get_db_connection", None)):
            return module
    return None


def run_schema_preflight() -> tuple[int, ...]:
    bot_module = _find_bot_module()
    if bot_module is None:
        raise RuntimeError("Bot DB module is not ready for schema migration preflight")
    applied = schema_migrations.run_pending(bot_module)
    if applied:
        logging.warning("Schema migrations applied at startup: %s", applied)
    return applied


def ensure_chat_member_updates(kwargs: dict) -> None:
    allowed = kwargs.get("allowed_updates")
    if allowed is None:
        return
    allowed_list = list(allowed)
    if UpdateType.CHAT_MEMBER not in allowed_list:
        allowed_list.append(UpdateType.CHAT_MEMBER)
    kwargs["allowed_updates"] = allowed_list


def prepare_polling_runtime(kwargs: dict) -> None:
    dialogue_followup_mode_patch.install()
    ensure_chat_member_updates(kwargs)


def _prepare_sticker_menu_runtime(application: Application) -> None:
    sticker_tuning_runtime.install()

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
        "Yayceslav stickers runtime ready: registry=%s; own-pack=50%% semantic sticker/text; shared cap=%s/hour",
        len(sticker_runtime.sticker_engine.STICKER_ORDER),
        sticker_runtime.STICKER_MAX_PER_WINDOW,
    )
    logging.warning("Scoped /help runtime ready: group/private/owner")


def prepare_application_runtime(application: Application) -> None:
    """Prepare application-owned features from one explicit startup path."""
    _prepare_sticker_menu_runtime(application)

    bot_module = _find_bot_module()
    if bot_module is not None and not claim_memory_v3.install_short_term_guard(bot_module):
        logging.warning("Claim memory v3 short-term guard: bot module not ready")

    unified_daily_title_runtime._prepare()
    title_reroll_runtime.prepare_application_runtime(application)
    monthly_social_runtime._prepare_application(application)
    relationship_experience_runtime._prepare_application(application)
    member_profile_runtime._prepare_application(application)
    episodic_memory_runtime._prepare_application(application)
    pairwise_relationship_runtime._prepare_application(application)
    whoami_profile_v3_runtime._prepare_application(application)
    whoami_profile_v4_runtime._prepare_application(application)

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

    if not date_grounding_runtime.install():
        logging.warning("Date grounding runtime: bot module not ready")

    if not social_priority_runtime.install():
        logging.warning("Social priority runtime: bot module not ready")
    owner_social_diagnostics_runtime.prepare_application_runtime(application)

    if not conflict_fsm_runtime.install():
        logging.warning("Conflict FSM runtime: bot module not ready")

    if not social_grounding_runtime.install():
        logging.warning("Social grounding runtime: bot module not ready")

    title_conflict_runtime.prepare_application_runtime(application)

    if not voice2_runtime.install():
        logging.warning("Voice 2.0 runtime: bot module not ready")

    search_enrichment_runtime.install()
    if not search_context_runtime.install():
        logging.warning("Search context runtime: bot module not ready")
    if not search_slang_runtime.install():
        logging.warning("Search slang runtime: bot module not ready")
    if not lexical_search_v3.install():
        logging.warning("Lexical search v3: bot module not ready")
    evidence_grounding_runtime.prepare_application_runtime(application)

    fight_routing_v3.prepare_application_runtime(application)

    if not fight_memory_afterburner_v2.install():
        logging.warning("Fight memory afterburner v2: install failed")

    if not rage_pacing_runtime.install():
        logging.warning("RAGE pacing runtime: install failed")

    if not roast_engine_runtime.install():
        logging.warning("Roast engine v1 runtime: bot module not ready")

    chat_digest_runtime.prepare_application_runtime(application)
    roast_target_runtime.prepare_application_runtime(application)
    natural_router_runtime.prepare_application_runtime(application)
    social_grounding_runtime.prepare_application_runtime(application)
    recent_video_note_runtime.prepare_application_runtime(application)

    if not shared_banter_runtime.install():
        logging.warning("Shared banter runtime: bot module not ready")

    # Install last: this layer only arbitrates narrow cross-runtime regressions
    # after all owners (search, fight, roast, social, delivery) are already set.
    if not live_chat_regression_runtime.install():
        logging.warning("Live-chat regression guard: bot module not ready")


def _install_preflight_hook() -> None:
    if getattr(Application, "_yayceslav_schema_preflight_installed", False):
        return

    original_run_polling = Application.run_polling

    def run_polling_with_schema_preflight(self, *args, **kwargs):
        try:
            run_schema_preflight()
        except Exception:
            logging.exception("Schema migration preflight failed; polling not started")
            raise
        prepare_polling_runtime(kwargs)
        prepare_application_runtime(self)
        return original_run_polling(self, *args, **kwargs)

    Application.run_polling = run_polling_with_schema_preflight
    Application._yayceslav_schema_preflight_installed = True


_install_preflight_hook()
