"""Group-first sticker policy for Yayceslav.

The live product currently lives in Telegram groups.  Older sticker layers grew
several independent selection paths (direct-question replacement, background
semantics, post-answer tags and a RAGE wrapper).  The result was counter-
intuitive: replies to Yayceslav bypassed the richest semantic path, fatigue
questions had a singleton ``tyazhelo_tyazhelo`` answer, and the Aug19 repeated-
insult sticker was hidden underneath the outer fight wrapper.

This module is the final outgoing policy for GROUP/SUPERGROUP text replies only.
It deliberately reuses the existing sticker catalog, conflict FSM, delivery and
anti-spam ledgers.  It adds no model call, database table or second fight state.

Rules:
- group questions are answered with text first; a sticker may be a punchline;
- normal post-answer stickers use the existing semantic event registry;
- recent outgoing sticker keys are remembered in bounded RAM to avoid repeats;
- RAGE keeps the two guaranteed visual beats but uses a broader funny pool,
  including the Aug19 repeated-insult sticker;
- serious text and quiet hours remain sticker-free.
"""

from __future__ import annotations

from collections import defaultdict, deque
import functools
import logging
import random
import re
import time
from typing import Any, Iterable

from telegram.constants import ChatType

import conflict_fsm_runtime
import fight_mode_v2_tuning
import sticker_engine
import sticker_post_runtime
import sticker_runtime


_INSTALLED = False

RECENT_STICKER_HISTORY = 5
NORMAL_DIRECT_POST_CHANCE = 0.20

# ``sticker_engine.detect_event(..., direct=True)`` intentionally labels every
# <=4-word direct message as ``direct_ping``.  That is fine for a dedicated ping
# listener, but too broad for post-answer group punchlines: normal replies such
# as ``дюна вильнева`` or ``сделай ещё`` must not randomly get ЧЁ НАДО / НУ И ЧЁ.
# Only explicit contextless pings are allowed to synthesize ``direct_ping`` here.
_DIRECT_PING_RE = re.compile(
    r"^\s*(?:"
    r"(?:эй[,.!?\s-]*)?(?:яйцеслав\w*|бот|бобр\w*|курва)"
    r"(?:\s+(?:ты\s+)?(?:тут|жив|живой))?"
    r"|ау|алло|ну"
    r")\s*[?!.]*\s*$",
    re.IGNORECASE,
)

# These events are safe as a small visual punchline after a normal text answer.
# Explicit dismissal/shut-up/fight events stay out of normal chat; they belong
# to the conflict policy below.
NORMAL_POST_EVENTS = frozenset(
    {
        "direct_ping",
        "confusion",
        "waiting",
        "swagger",
        "epic_victory",
        "fatigue",
        "self_own",
        "perfection",
        "ramble",
        "weak_take",
        "so_what",
        "aura_loss",
        "approval",
        "agreement",
        "dry_reply",
        "fail",
        "outplayed",
        "proof",
        "lets_go",
        "alarm",
        "respect_f",
        "aura_gain",
        "fiasko",
        "salt",
        "skill_issue",
        "friday",
        "skoof",
        "ancestor",
        "money",
        "cringe",
        # Aug19 semantic events.  They simply do not exist before that catalog
        # extension is installed, so keeping the names here is harmless.
        "milf",
        "shaking",
        "conspiracy",
        "doom",
        "absurdity",
    }
)

RAGE_RELEVANT_EVENTS = frozenset(
    {
        "hard_dismissal",
        "shut_up_escalated",
        "shut_up",
        "weak_take",
        "skill_issue",
        "cringe",
        "fail",
        "fiasko",
        "outplayed",
        "self_own",
        "salt",
        "aura_loss",
        "no_talk",
        "fight",
        "swagger",
    }
)

# Funny/combative defaults for a real repeated fight.  Aug19-only keys are
# filtered against the live semantic registry before selection, so tests and
# unusual startup paths that still have the original 37-pack remain safe.
RAGE_FUNNY_POOL = (
    "nu_i_suka_zhe_ty",
    "slabyy_zahod",
    "skill_issue",
    "krinzh",
    "obtekay",
    "kto_opyat_ne_spravilsya",
    "pereigral_i_unichtozhil_new",
    "fa_watafa",
    "ne_vyvez",
    "pereigral_i_unichtozhil",
)

_RECENT_BY_CHAT: dict[int, deque[str]] = defaultdict(
    lambda: deque(maxlen=RECENT_STICKER_HISTORY)
)


def reset_recent() -> None:
    """Test/debug helper; recent diversity memory is intentionally RAM-only."""

    _RECENT_BY_CHAT.clear()


def recent_stickers(chat_id: int) -> tuple[str, ...]:
    return tuple(_RECENT_BY_CHAT.get(int(chat_id), ()))


def record_recent(chat_id: int, sticker_key: str) -> None:
    key = str(sticker_key or "").strip()
    if key:
        _RECENT_BY_CHAT[int(chat_id)].append(key)


def _known_options(options: Iterable[str]) -> list[str]:
    semantics = sticker_engine.STICKER_SEMANTICS
    return [str(key) for key in options if str(key) in semantics]


def choose_fresh(
    options: Iterable[str],
    chat_id: int,
    *,
    extra_exclude: Iterable[str] = (),
    rng: Any = random,
) -> str | None:
    """Prefer a key not used recently; never invent a semantic substitute."""

    known = list(dict.fromkeys(_known_options(options)))
    if not known:
        return None

    hard_exclude = {str(key) for key in extra_exclude}
    recent = set(recent_stickers(chat_id))

    fresh = [key for key in known if key not in hard_exclude and key not in recent]
    if fresh:
        return rng.choice(fresh)

    # A fight may have exhausted the recent-history set but should still avoid
    # repeating a sticker already used in the same RAGE session.
    session_fresh = [key for key in known if key not in hard_exclude]
    if session_fresh:
        return rng.choice(session_fresh)

    # Last resort for a singleton semantic event.  Normal post-answer policy may
    # decide to suppress this repeat; RAGE can still use it if every option was
    # consumed in-session.
    return rng.choice(known)


def _event_key(
    event: str | None,
    chat_id: int,
    *,
    extra_exclude: Iterable[str] = (),
) -> str | None:
    if not event:
        return None
    return choose_fresh(
        sticker_engine.EVENT_STICKERS.get(event, ()),
        chat_id,
        extra_exclude=extra_exclude,
    )


def _normal_group_event(source: str, *, direct: bool) -> str | None:
    """Use semantic evidence first; synthesize direct_ping only for real pings."""

    event = sticker_engine.detect_event(source, direct=False)
    if event is None and direct and _DIRECT_PING_RE.fullmatch(source):
        return "direct_ping"
    return event


def normal_post_key(
    source_user_text: str,
    answer_text: str,
    *,
    chat_id: int,
    direct: bool,
) -> str | None:
    """Select a normal group punchline from existing semantic evidence."""

    source = str(source_user_text or "").strip()
    answer = str(answer_text or "").strip()
    if not source or not answer:
        return None
    if sticker_engine.is_serious_text(source) or sticker_engine.is_serious_text(answer):
        return None

    event = _normal_group_event(source, direct=bool(direct))

    # Preserve answer-aware tags (BАЗА, PEREIGRAL, Aug19 doom/problem tags).
    special = sticker_post_runtime.choose_post_text_tag(source, answer)
    if special:
        if special not in recent_stickers(chat_id):
            return special
        # Do not hammer the same special sticker.  If the source event offers a
        # different semantic visual, use it; otherwise skip this turn.
        if event in NORMAL_POST_EVENTS:
            alternative = _event_key(event, chat_id, extra_exclude=(special,))
            if alternative and alternative != special:
                return alternative
        return None

    if event not in NORMAL_POST_EVENTS:
        return None
    return _event_key(event, chat_id)


def rage_pool(source_user_text: str) -> tuple[str, ...]:
    """Return a contextual fight pool, with funny defaults always available."""

    source = str(source_user_text or "").strip()
    event = sticker_engine.detect_event(source, direct=True)
    contextual: tuple[str, ...] = ()
    if event in RAGE_RELEVANT_EVENTS:
        contextual = tuple(sticker_engine.EVENT_STICKERS.get(event, ()))

    # RAGE means repeated directed hostility by definition.  This makes the
    # Aug19 repeated-insult visual reachable inside the final fight policy rather
    # than hiding it beneath the old wrapper chain.
    combined = contextual + RAGE_FUNNY_POOL
    return tuple(dict.fromkeys(_known_options(combined)))


def _is_group(chat: Any) -> bool:
    return bool(
        chat
        and getattr(chat, "type", None) in (ChatType.GROUP, ChatType.SUPERGROUP)
    )


def _is_rage(chat_id: int, user_id: int) -> bool:
    try:
        return (
            conflict_fsm_runtime.phase(int(chat_id), int(user_id))
            is conflict_fsm_runtime.ConflictPhase.RAGE
        )
    except Exception:
        return False


async def maybe_send_group_post_text_tag(
    update: Any,
    context: Any,
    source_user_text: str,
    answer_text: str,
) -> bool:
    """Final group post-answer sticker policy used by ``send_answer``."""

    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    if not _is_group(chat) or not user or getattr(user, "is_bot", False):
        return False

    source = str(source_user_text or "").strip()
    answer = str(answer_text or "").strip()
    if not source or not answer:
        return False
    if sticker_engine.is_serious_text(source) or sticker_engine.is_serious_text(answer):
        return False
    if sticker_runtime._quiet_hours_msk():
        return False

    now = time.monotonic()

    if _is_rage(chat.id, user.id):
        state = fight_mode_v2_tuning._rage_sticker_state(context, user.id, now)
        turns = int(state.get("turns", 0))
        sent_count = int(state.get("sent", 0))
        if sent_count >= fight_mode_v2_tuning.RAGE_STICKER_MAX_PER_SESSION:
            return False

        guaranteed = (
            sent_count < fight_mode_v2_tuning.RAGE_GUARANTEED_STICKERS
            and (
                sent_count == 0
                or turns >= fight_mode_v2_tuning.RAGE_SECOND_STICKER_FROM_TURN
            )
        )
        if not guaranteed:
            if random.random() >= fight_mode_v2_tuning.RAGE_OPTIONAL_STICKER_CHANCE:
                return False
            if not sticker_runtime.sticker_slot_allowed(chat.id, user.id, now):
                return False

        used = tuple(str(key) for key in state.get("used_keys", ()))
        sticker_key = choose_fresh(
            rage_pool(source),
            chat.id,
            extra_exclude=used,
        )
        if not sticker_key:
            return False

        try:
            delivered = await sticker_runtime.reply_sticker_by_key(
                update, context, sticker_key
            )
        except Exception as error:
            logging.warning("Group sticker v2 RAGE send failed key=%s: %s", sticker_key, error)
            return False
        if not delivered:
            return False

        sticker_runtime._record_sticker_slot(chat.id, user.id, now)
        state["sent"] = sent_count + 1
        next_used = list(state.get("used_keys", ()))
        next_used.append(sticker_key)
        state["used_keys"] = next_used[-max(1, len(RAGE_FUNNY_POOL)):]
        logging.info(
            "Group sticker v2 RAGE: key=%s guaranteed=%s turn=%s sent=%s chat=%s user=%s",
            sticker_key,
            guaranteed,
            turns,
            state["sent"],
            chat.id,
            user.id,
        )
        return True

    direct = sticker_runtime._is_direct_call(update, context)
    sticker_key = normal_post_key(
        source,
        answer,
        chat_id=chat.id,
        direct=direct,
    )
    if not sticker_key:
        return False

    chance = (
        NORMAL_DIRECT_POST_CHANCE
        if direct
        else float(sticker_post_runtime.POST_TEXT_TAG_CHANCE)
    )
    if random.random() >= chance:
        return False
    if not sticker_runtime.sticker_slot_allowed(chat.id, user.id, now):
        return False

    try:
        delivered = await sticker_runtime.reply_sticker_by_key(
            update, context, sticker_key
        )
    except Exception as error:
        logging.warning("Group sticker v2 post-answer send failed key=%s: %s", sticker_key, error)
        return False
    if not delivered:
        return False

    sticker_runtime._record_sticker_slot(chat.id, user.id, now)
    logging.info(
        "Group sticker v2 post-answer: key=%s direct=%s chat=%s user=%s",
        sticker_key,
        direct,
        chat.id,
        user.id,
    )
    return True


def _patch_delivery_tracking() -> None:
    original = sticker_runtime.reply_sticker_by_key
    if getattr(original, "_yayceslav_group_sticker_v2_tracking", False):
        return

    @functools.wraps(original)
    async def reply_and_remember(update: Any, context: Any, sticker_key: str) -> bool:
        sent = await original(update, context, sticker_key)
        if sent:
            chat = getattr(update, "effective_chat", None)
            if chat is not None:
                record_recent(int(chat.id), str(sticker_key))
        return bool(sent)

    reply_and_remember._yayceslav_group_sticker_v2_tracking = True
    sticker_runtime.reply_sticker_by_key = reply_and_remember


def _patch_group_question_text_first() -> None:
    original = sticker_runtime.direct_question_sticker_listener
    if getattr(original, "_yayceslav_group_text_first", False):
        return

    @functools.wraps(original)
    async def text_first_in_groups(update: Any, context: Any) -> None:
        chat = getattr(update, "effective_chat", None)
        if _is_group(chat):
            # Do not replace a useful group answer with a sticker.  The normal
            # answer path will call our post-answer policy afterwards.
            return
        return await original(update, context)

    text_first_in_groups._yayceslav_group_text_first = True
    sticker_runtime.direct_question_sticker_listener = text_first_in_groups


def install() -> bool:
    """Become the final outgoing group sticker policy after fight-v2 is loaded."""

    global _INSTALLED
    if _INSTALLED:
        return True

    _patch_delivery_tracking()
    _patch_group_question_text_first()

    # Replace, rather than wrap, the accumulated Aug19/fight-v2 post-answer
    # chain.  All required semantics/state are reused above, so there is one
    # visible owner for group outgoing selection from this point onward.
    sticker_post_runtime.maybe_send_post_text_tag = maybe_send_group_post_text_tag

    _INSTALLED = True
    logging.warning(
        "Group sticker behavior v2 ready: text-first group answers, semantic post-tags, "
        "5-key recent diversity, expanded distinct RAGE pool"
    )
    return True
