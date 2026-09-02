"""Late startup hook for the live voice bridge.

Imported by the small rate-limit runtime during application preparation. It
wraps self_canon_runtime.install so the voice bridge is installed immediately
after self-canon, without changing the large central bootstrap file.
"""

from __future__ import annotations

import functools
from typing import Any

import self_canon_runtime
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


def _install_voice_bridge_after_self_canon(bot_module: Any | None = None) -> None:
    if not voice_live_bridge_runtime.install(bot_module):
        return
    # Bridge first replaces VoiceDecision with the wider schema; then replace the
    # old normalizer which hard-capped/flattened direct answers at 1000 chars.
    voice2_runtime._normalize_decision = _normalize_live_decision


def install_hook() -> bool:
    global _HOOKED
    if _HOOKED:
        return True

    original = self_canon_runtime.install
    if getattr(original, "_yayceslav_voice_live_hook", False):
        _HOOKED = True
        return True

    @functools.wraps(original)
    def self_canon_then_voice(*args: Any, **kwargs: Any) -> bool:
        result = bool(original(*args, **kwargs))
        if result:
            bot_module = args[0] if args else kwargs.get("bot_module")
            _install_voice_bridge_after_self_canon(bot_module)
        return result

    self_canon_then_voice._yayceslav_voice_live_hook = True
    self_canon_runtime.install = self_canon_then_voice
    _HOOKED = True
    return True


install_hook()
