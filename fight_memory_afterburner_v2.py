"""Grounded fight-memory enrichment for the existing v3 afterburner.

This module does not own conflict state, timers, or model calls.  It enriches the
single v3 afterburner with a bounded callback extracted only from text the target
actually wrote during the current fight. Sensitive claims are excluded wholesale
via claim_memory_v3 so bait cannot become biography.
"""

from __future__ import annotations

from collections import Counter
import functools
import html
import random
import re
from typing import Any

import claim_memory_v3
import fight_routing_v3

_INSTALLED = False

_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9-]{4,}")
_STOPWORDS = {
    "который", "которая", "которые", "потому", "просто", "тебя", "тебе",
    "твой", "твоя", "твою", "этот", "эта", "это", "чтобы", "будешь",
    "будет", "было", "есть", "меня", "мне", "тогда", "сейчас", "опять",
    "дальше", "вообще", "реально", "факту", "через", "после", "перед",
}


def safe_fight_texts(texts: list[str]) -> list[str]:
    """Return bounded observed fight lines safe to reuse as callbacks."""
    result: list[str] = []
    for raw in texts[-8:]:
        clean = " ".join(str(raw or "").split()).strip()
        if not clean or claim_memory_v3.is_sensitive_claim_text(clean):
            continue
        result.append(clean[:180])
    return result[-6:]


def callback_token(texts: list[str]) -> str:
    """Pick a repeated target-authored token; never infer a personal fact."""
    safe = safe_fight_texts(texts)
    counts: Counter[str] = Counter()
    surface: dict[str, str] = {}
    for line in safe:
        seen: set[str] = set()
        for token in _WORD_RE.findall(line):
            key = token.lower().replace("ё", "е")
            if key in _STOPWORDS or key in seen:
                continue
            seen.add(key)
            counts[key] += 1
            surface.setdefault(key, token)

    repeated = [(count, key) for key, count in counts.items() if count >= 2]
    if not repeated:
        return ""
    repeated.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    return surface[repeated[0][1]][:40]


def fight_event(texts: list[str]) -> str:
    safe = safe_fight_texts(texts)
    if any(fight_routing_v3.is_bait_reveal(line) for line in safe):
        return "bait_reveal"
    return ""


def grounded_afterburner_line(state: Any, fallback: Any) -> str:
    """Use observed repetition when possible, otherwise preserve v3 behavior."""
    token = callback_token(list(getattr(state, "fight_texts", ()) or ()))
    event = fight_event(list(getattr(state, "fight_texts", ()) or ()))
    if not token and not event:
        return fallback(state)

    mention = fight_routing_v3._mention_html(state)
    spoke_after = bool(getattr(state, "target_spoke_after", False))
    if token:
        quoted = html.escape(token)
        if spoke_after:
            variants = (
                f"{mention}, с остальными голос нашёлся? А «{quoted}» мне так и оставил вместо концовки.",
                f"{mention}, смотрю, снова разговорчивый. «{quoted}» уже закончился или ещё будет второй сезон?",
                f"{mention}, на других переключился бодро. А своё «{quoted}» до финала не дотащил.",
            )
        else:
            variants = (
                f"{mention}, куда пропал? «{quoted}» так уверенно повторял, а концовку забыл.",
                f"{mention}, ну что там с «{quoted}»? Повтор был мощный, финал куда-то делся.",
                f"{mention}, «{quoted}» кончилось — и ты вместе с ним?",
            )
        return random.choice(variants)

    # A revealed bait is remembered only as an event, never by repeating its claim.
    if spoke_after:
        return f"{mention}, с остальными уже разговорчивый? А тот байт объявил и наш раунд бросил без финала."
    return f"{mention}, байт торжественно раскрыл — и сразу исчез. Это уже была концовка?"


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    original = fight_routing_v3._pick_afterburner_line
    if getattr(original, "_yayceslav_fight_memory_v2", False):
        _INSTALLED = True
        return True

    @functools.wraps(original)
    def pick_grounded(state: Any) -> str:
        return grounded_afterburner_line(state, original)

    pick_grounded._yayceslav_fight_memory_v2 = True
    fight_routing_v3._pick_afterburner_line = pick_grounded
    _INSTALLED = True
    return True
