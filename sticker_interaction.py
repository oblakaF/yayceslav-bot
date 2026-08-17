"""Pure interaction rules for Yayceslav's own Telegram sticker pack."""

from __future__ import annotations

import random
import re
from typing import Final

import sticker_engine


QUESTION_STICKER_REPLY_CHANCE: Final = 0.05

# When a direct user question wins the 5% sticker slot and has no stronger
# semantic event, choose one of these dry character replies instead of text.
QUESTION_REPLY_STICKERS: Final[tuple[str, ...]] = (
    "che_nado",
    "nu_i_che",
    "mda",
    "yasno",
    "baza",
    "slabyy_zahod",
)

# Incoming sticker from Yayceslav's own pack -> possible sticker comebacks.
# Stickers from any other set never enter this map and are ignored by runtime.
OWN_STICKER_COMEBACKS: Final[dict[str, tuple[str, ...]]] = {
    "che_nado": ("nu_i_che", "mda"),
    "zavali_varezhku": ("ne_bazar", "obtekay"),
    "po_delu_govori": ("baza", "yasno"),
    "slabyy_zahod": ("obtekay", "krinzh"),
    "idi_lesom": ("zavali_varezhku", "obtekay"),
    "nu_i_che": ("yasno", "mda"),
    "minus_aura": ("krinzh", "obtekay"),
    "yayceslav_odobryaet": ("baza", "horosh"),
    "baza": ("yayceslav_odobryaet", "horosh"),
    "mda": ("yasno", "krinzh"),
    "yasno": ("mda", "baza"),
    "ne_vyvez": ("eto_fiasko_bratan", "obtekay"),
    "pereigral_i_unichtozhil": ("f", "horosh"),
    "horosh": ("plus_aura", "yayceslav_odobryaet"),
    "gde_prufy": ("po_delu_govori", "mda"),
    "za_dvizh": ("horosh", "plus_aura"),
    "kod_krasnyy": ("f", "eto_fiasko_bratan"),
    "f": ("horosh", "baza"),
    "plus_aura": ("yayceslav_odobryaet", "horosh"),
    "eto_fiasko_bratan": ("ne_vyvez", "f"),
    "obtekay": ("skill_issue", "mda"),
    "shcha_razebu": ("ne_bazar", "slabyy_zahod"),
    "ne_bazar": ("zavali_varezhku", "mda"),
    "skill_issue": ("obtekay", "slabyy_zahod", "zavali_varezhku"),
    "pyatnitsa": ("za_dvizh", "horosh"),
    "tyazhelyy_skuf": ("krinzh", "baza"),
    "slava_prashchuru": ("baza", "yayceslav_odobryaet"),
    "derzhi_nishchiy": ("mda", "obtekay"),
    "krinzh": ("minus_aura", "slabyy_zahod"),
}

_QUESTION_START_RE = re.compile(
    r"^\s*(?:яйцеслав\w*[,:!?\s-]*)?(?:"
    r"кто|что|ч[её]|где|куда|откуда|когда|зачем|почему|как|сколько|"
    r"какой|какая|какие|какое|чей|чья|чьи|можно|можешь|можете|"
    r"умеешь|умеете|стоит\s+ли|правда\s+ли|нужно\s+ли|надо\s+ли|"
    r"скаж(?:и|ите)|объясни|расскажи"
    r")\b",
    re.IGNORECASE,
)


def is_question(text: str) -> bool:
    """Cheap local gate: obvious questions only, no Gemini call."""

    stripped = (text or "").strip()
    if not stripped:
        return False
    if "?" in stripped:
        return True
    return bool(_QUESTION_START_RE.search(stripped))


def choose_question_sticker(
    text: str,
    *,
    rng=random,
) -> str:
    """Prefer a semantic event sticker; otherwise use the dry question pool."""

    event = sticker_engine.detect_event(text, direct=False)
    if event:
        semantic = sticker_engine.EVENT_STICKERS.get(event)
        if semantic:
            return rng.choice(semantic)
    return rng.choice(QUESTION_REPLY_STICKERS)


def choose_own_pack_comeback(
    incoming_sticker_key: str,
    *,
    rng=random,
) -> str | None:
    options = OWN_STICKER_COMEBACKS.get(incoming_sticker_key)
    if not options:
        return None
    return rng.choice(options)


def validate_interaction_map() -> None:
    known = set(sticker_engine.STICKER_ORDER)

    assert 0.0 <= QUESTION_STICKER_REPLY_CHANCE <= 1.0
    assert set(QUESTION_REPLY_STICKERS) <= known
    assert set(OWN_STICKER_COMEBACKS) == known

    unknown = {
        key
        for replies in OWN_STICKER_COMEBACKS.values()
        for key in replies
        if key not in known
    }
    if unknown:
        raise RuntimeError(f"Unknown comeback sticker keys: {sorted(unknown)}")


validate_interaction_map()
