"""Keep sensitive one-off claims out of automatic callback memory.

Group short-term chat history still remembers what was said for conversational
continuity, but automatic member callback/theme memory must not turn a bait such
as "собака умерла" into a durable personal fact.  Explicit /remember_me remains
the controlled path for facts the user actually wants saved.
"""

from __future__ import annotations

import logging

import member_profile_runtime


_EXTRA_SENSITIVE_FRAGMENTS = (
    "умер", "смерт", "похорон", "травм", "кровотеч", "сепсис",
    "рана", "ранен", "разрыв", "операц", "ветеринар", "инфекц",
)


def install() -> None:
    current = tuple(getattr(member_profile_runtime, "_SENSITIVE_FRAGMENTS", ()))
    merged = current + tuple(
        fragment for fragment in _EXTRA_SENSITIVE_FRAGMENTS if fragment not in current
    )
    member_profile_runtime._SENSITIVE_FRAGMENTS = merged
    logging.warning(
        "Claim memory v3 ready: sensitive/death/injury claims excluded from automatic callback memory"
    )


install()
