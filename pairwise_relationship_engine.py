"""Pure classification of a reply-chain interaction between two members.

Data-only for now: pairwise_relationship_runtime records who replies to
whom, but nothing yet reads pair_label() into a live prompt. Detection
reuses reputation_engine's generic Russian praise/abuse phrase lists,
which were tuned for messages directed at the bot — applied to peer
replies the hostile/positive split is a rough signal, not a confident
one, so surfacing it in conversation is a deliberate later decision,
not an automatic consequence of this data existing.
"""

from __future__ import annotations

PAIR_MENTION_MIN_REPLIES = 15
_HOSTILE_RATIO_THRESHOLD = 0.3
_POSITIVE_RATIO_THRESHOLD = 0.3


def pair_label(reply_count: int, hostile_count: int, positive_count: int) -> str | None:
    replies = max(0, int(reply_count or 0))
    if replies < PAIR_MENTION_MIN_REPLIES:
        return None

    hostile = max(0, int(hostile_count or 0))
    positive = max(0, int(positive_count or 0))

    if hostile / replies >= _HOSTILE_RATIO_THRESHOLD:
        return "часто спорят"
    if positive / replies >= _POSITIVE_RATIO_THRESHOLD:
        return "часто шутят вместе"
    return "постоянно переписываются"
