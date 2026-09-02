"""Late startup hook for self-canon v2, memory, voice, and music bridges.

Imported by the small rate-limit runtime during application preparation. It
wraps self_canon_runtime.install so the personality-inertia layer is installed
immediately after V1 self-canon, then Personality Architecture v2 establishes
layer ownership, the immutable mythic-Rus core and canon-aware everyday decision
layer are added above chat-local canon, the obsolete character selector is
neutralized, the live voice bridge is installed, persistent tiered memory wraps
the common stores, rare self-development can inspect that durable semantic
history, and finally the text/voice/video-note bridge sits outermost so semantic
media text is what gets persisted.

The same late hook installs the lyrics bridge before ``music_runtime`` registers
its application handler. This keeps the stable MusicBrainz handler as the single
music route while adding LRCLIB/Musixmatch analysis as an optional wrapper.
"""

from __future__ import annotations

import functools
from typing import Any

import canon_decision_runtime
import gemini_stability_runtime
import legacy_character_retirement_runtime
import music_lyrics_bridge_runtime
import mythic_rus_core_runtime
import persistent_tiered_memory_runtime
import personality_architecture_v2_runtime
import self_canon_runtime
import self_canon_v2_runtime
import self_development_runtime
import unified_multimodal_context_runtime
import voice2_runtime
import voice_live_bridge_runtime


_HOOKED = False


def _normalize_live_decision(
    decision: Any,
    *,
    video_note: bool = False,
):
    """Keep useful voice answers long/formatted while bounding control fields."""

    transcript = " ".join(str(decision.transcript or "").split()).strip()[:700]
    query = " ".join(str(decision.search_query or "").split()).strip()[:220]
    answer = str(decision.answer or "").strip()[: voice_live_bridge_runtime.VOICE_LIVE_ANSWER_MAX_CHARS]
    memory_summary = (
        voice2_runtime._normalize_memory_summary(str(decision.memory_summary or ""))
        if video_note
        else ""
    )

    if bool(decision.needs_search):
        if not query:
            query = transcript[:220]
        answer = ""
    else:
        query = ""

    wants_voice = bool(decision.wants_voice) or voice2_runtime._transcript_explicitly_requests_voice(
        transcript
    )

    return voice2_runtime.VoiceDecision(
        transcript=transcript,
        needs_search=bool(decision.needs_search),
        search_query=query,
        answer=answer,
        wants_voice=wants_voice,
        memory_summary=memory_summary,
    )


def _install_personality_layers_after_self_canon(bot_module: Any | None = None) -> None:
    if not self_canon_v2_runtime.install(bot_module):
        return
    if not personality_architecture_v2_runtime.install(bot_module):
        return
    if not mythic_rus_core_runtime.install(bot_module):
        return
    if not canon_decision_runtime.install(bot_module):
        return
    if not legacy_character_retirement_runtime.install(bot_module):
        return
    if not voice_live_bridge_runtime.install(bot_module):
        return
    # Persistent memory must wrap remember_message BEFORE the multimodal bridge.
    # Rare self-development is installed after it so its evidence query always
    # has the durable semantic-history table available.
    if not persistent_tiered_memory_runtime.install(bot_module):
        return
    if not self_development_runtime.install(bot_module):
        return
    if not unified_multimodal_context_runtime.install(bot_module):
        return
    # Bridge first replaces VoiceDecision with the wider schema; then replace the
    # old normalizer which hard-capped/flattened direct answers at 1000 chars.
    voice2_runtime._normalize_decision = _normalize_live_decision
    # VoiceLiveDecision replaces the original schema class, so install the
    # wrapper-tolerant JSON validator again on the live schema after replacement.
    gemini_stability_runtime.install_voice_json_recovery()


def install_hook() -> bool:
    global _HOOKED
    if _HOOKED:
        return True

    # Install provider-neutral lyrics routing before music_runtime registers its
    # application handler later in runtime_bootstrap.prepare_application_runtime.
    music_lyrics_bridge_runtime.install()

    # Install model-capacity routing and daily-content JSON recovery early in
    # application preparation. Voice schema recovery is refreshed again after
    # VoiceLiveDecision is installed below.
    gemini_stability_runtime.install()

    original = self_canon_runtime.install
    if getattr(original, "_yayceslav_voice_live_hook", False):
        _HOOKED = True
        return True

    @functools.wraps(original)
    def self_canon_then_v2_then_voice(*args: Any, **kwargs: Any) -> bool:
        result = bool(original(*args, **kwargs))
        if result:
            bot_module = args[0] if args else kwargs.get("bot_module")
            _install_personality_layers_after_self_canon(bot_module)
        return result

    self_canon_then_v2_then_voice._yayceslav_voice_live_hook = True
    self_canon_runtime.install = self_canon_then_v2_then_voice
    _HOOKED = True
    return True


install_hook()
