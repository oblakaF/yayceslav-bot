"""Pure interaction rules for Yayceslav's own Telegram sticker pack."""

from __future__ import annotations

import random
import re
from typing import Final

import sticker_engine

# This is a maximum slot, not a promise to send a sticker every 20 questions.
# A qualifying question must ALSO have a semantically appropriate sticker.
QUESTION_STICKER_REPLY_CHANCE: Final = 0.05

# Direct-question semantics are intentionally conservative. Generic questions
# have no sticker candidate and therefore stay normal text answers.
QUESTION_EVENT_STICKERS: Final[dict[str, tuple[str, ...]]] = {
    "proof": ("gde_prufy",),
    "waiting": ("14_minut_blyat", "tyazhelo_tyazhelo"),
    "confusion": ("ty_po_moemu_pereputal",),
    "perfection": ("doebu_do_ideala",),
    "fatigue": ("tyazhelo_tyazhelo",),
    "swagger": ("ty_dumal_zvezdnyy_lord",),
    "epic_victory": ("goyda_mars_nash", "plus_aura"),
    "self_own": ("nadel_tebya_na_suk", "pereigral_i_unichtozhil"),
    "skill_issue": ("skill_issue",),
    "cringe": ("krinzh",),
    "aura_loss": ("minus_aura",),
    "aura_gain": ("plus_aura",),
    "fiasko": ("eto_fiasko_bratan",),
    "fail": ("ne_vyvez", "eto_fiasko_bratan"),
    "alarm": ("kod_krasnyy",),
    "friday": ("pyatnitsa",),
    "ancestor": ("slava_prashchuru",),
    "money": ("derzhi_nishchiy",),
    "skoof": ("tyazhelyy_skuf",),
}

# Incoming sticker from Yayceslav's own pack -> contextually sensible sticker
# comebacks. Foreign packs never enter this map and are ignored by runtime.
OWN_STICKER_COMEBACKS: Final[dict[str, tuple[str, ...]]] = {
    "ty_po_moemu_pereputal": ("gde_prufy", "mda", "yasno"),
    "14_minut_blyat": ("tyazhelo_tyazhelo", "mda", "yasno"),
    "ty_dumal_zvezdnyy_lord": ("minus_aura", "krinzh", "slabyy_zahod"),
    "goyda_mars_nash": ("za_dvizh", "plus_aura", "horosh"),
    "vremya_zavalit_ebalo": ("ne_bazar", "zavali_varezhku", "mda"),
    "tyazhelo_tyazhelo": ("f", "yasno", "mda"),
    "nadel_tebya_na_suk": ("pereigral_i_unichtozhil", "obtekay", "horosh"),
    "doebu_do_ideala": ("horosh", "plus_aura", "yayceslav_odobryaet"),
    "idi_nahui": ("obtekay", "zavali_varezhku", "ne_bazar"),
    "che_nado": ("nu_i_che", "mda"),
    "zavali_varezhku": ("ne_bazar", "obtekay", "idi_nahui"),
    "po_delu_govori": ("baza", "yasno"),
    "slabyy_zahod": ("obtekay", "krinzh"),
    "nu_i_che": ("yasno", "mda"),
    "minus_aura": ("krinzh", "obtekay"),
    "yayceslav_odobryaet": ("baza", "horosh"),
    "baza": ("yayceslav_odobryaet", "horosh"),
    "mda": ("yasno", "krinzh"),
    "yasno": ("mda", "baza"),
    "ne_vyvez": ("eto_fiasko_bratan", "obtekay"),
    "pereigral_i_unichtozhil": ("nadel_tebya_na_suk", "f", "horosh"),
    "horosh": ("plus_aura", "yayceslav_odobryaet"),
    "gde_prufy": ("po_delu_govori", "ty_po_moemu_pereputal", "mda"),
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
    "tyazhelyy_skuf": ("krinzh", "baza", "tyazhelo_tyazhelo"),
    "slava_prashchuru": ("baza", "yayceslav_odobryaet", "goyda_mars_nash"),
    "derzhi_nishchiy": ("mda", "obtekay", "horosh"),
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


def choose_question_sticker(text: str, *, rng=random) -> str | None:
    """Return a semantically valid sticker or None for a normal text answer.

    This is intentionally NOT a generic random sticker pool. If the question
    has no explicit sticker-worthy semantic event, the bot should answer text.
    """
    event = sticker_engine.detect_event(text, direct=False)
    options = QUESTION_EVENT_STICKERS.get(event or "")
    if not options:
        return None
    return rng.choice(options)


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

    assert QUESTION_STICKER_REPLY_CHANCE == 0.05
    assert set(OWN_STICKER_COMEBACKS) == known

    unknown_question = {
        key
        for replies in QUESTION_EVENT_STICKERS.values()
        for key in replies
        if key not in known
    }
    if unknown_question:
        raise RuntimeError(f"Unknown question sticker keys: {sorted(unknown_question)}")

    unknown_comeback = {
        key
        for replies in OWN_STICKER_COMEBACKS.values()
        for key in replies
        if key not in known
    }
    if unknown_comeback:
        raise RuntimeError(f"Unknown comeback sticker keys: {sorted(unknown_comeback)}")

    # Direct-question sticker selection must never escalate to our hardest
    # hostile stickers. Hostile text mode handles those conversations instead.
    hard = {"idi_nahui", "vremya_zavalit_ebalo"}
    question_outputs = {
        key for replies in QUESTION_EVENT_STICKERS.values() for key in replies
    }
    if hard & question_outputs:
        raise RuntimeError("Hard hostile stickers leaked into direct-question pool")


validate_interaction_map()
