"""Context map for Yayceslav's Telegram sticker pack.

The public pack is https://t.me/addstickers/yayceslav_stickers .
This module intentionally contains only pure detection / selection logic;
Telegram transport lives in sitecustomize.py so the huge bot.py does not
need an invasive rewrite.
"""

from __future__ import annotations

import random
import re
from typing import Final

STICKER_SET_NAME: Final = "yayceslav_stickers"
STICKER_PACK_URL: Final = "https://t.me/addstickers/yayceslav_stickers"

# Current order in the published pack. On first runtime lookup file_ids are
# persisted by canonical key, so later reordering the pack does not break the
# bot after it has learned the IDs once.
STICKER_ORDER: Final[tuple[str, ...]] = (
    "che_nado",
    "zavali_varezhku",
    "po_delu_govori",
    "slabyy_zahod",
    "idi_lesom",
    "nu_i_che",
    "minus_aura",
    "yayceslav_odobryaet",
    "baza",
    "mda",
    "yasno",
    "ne_vyvez",
    "pereigral_i_unichtozhil",
    "horosh",
    "gde_prufy",
    "za_dvizh",
    "kod_krasnyy",
    "f",
    "plus_aura",
    "eto_fiasko_bratan",
    "obtekay",
    "shcha_razebu",
    "ne_bazar",
    "skill_issue",
    "pyatnitsa",
    "tyazhelyy_skuf",
    "slava_prashchuru",
    "derzhi_nishchiy",
    "krinzh",
)

STICKER_LABELS: Final[dict[str, str]] = {
    "che_nado": "ЧЁ НАДО?",
    "zavali_varezhku": "ЗАВАЛИ ВАРЕЖКУ",
    "po_delu_govori": "ПО ДЕЛУ ГОВОРИ",
    "slabyy_zahod": "СЛАБЫЙ ЗАХОД",
    "idi_lesom": "ИДИ ЛЕСОМ",
    "nu_i_che": "НУ И ЧЁ?",
    "minus_aura": "МИНУС АУРА",
    "yayceslav_odobryaet": "ЯЙЦЕСЛАВ ОДОБРЯЕТ",
    "baza": "БАЗА",
    "mda": "МДА",
    "yasno": "ЯСНО",
    "ne_vyvez": "НЕ ВЫВЕЗ",
    "pereigral_i_unichtozhil": "ПЕРЕИГРАЛ И УНИЧТОЖИЛ",
    "horosh": "ХОРОШ",
    "gde_prufy": "ГДЕ ПРУФЫ?",
    "za_dvizh": "ЗА ДВИЖ!",
    "kod_krasnyy": "КОД КРАСНЫЙ",
    "f": "F",
    "plus_aura": "ПЛЮС АУРА",
    "eto_fiasko_bratan": "ЭТО ФИАСКО, БРАТАН",
    "obtekay": "ОБТЕКАЙ",
    "shcha_razebu": "ЩА РАЗЪЕБУ",
    "ne_bazar": "НЕ БАЗАРЬ",
    "skill_issue": "СКИЛЛ ИЩЬЮ",
    "pyatnitsa": "ПЯТНИЦА! ПОРА НАХУЯРИТЬСЯ",
    "tyazhelyy_skuf": "ТЯЖЁЛЫЙ СКУФ",
    "slava_prashchuru": "СЛАВА ПРАЩУРУ",
    "derzhi_nishchiy": "ДЕРЖИ, НИЩИЙ",
    "krinzh": "КРИНЖ",
}

# Draft event -> sticker pool. This is deliberately human-editable: the user
# can change only this table without touching Telegram runtime code.
EVENT_STICKERS: Final[dict[str, tuple[str, ...]]] = {
    "direct_ping": ("che_nado", "nu_i_che"),
    "shut_up": ("zavali_varezhku", "ne_bazar"),
    "ramble": ("po_delu_govori", "tyazhelyy_skuf"),
    "weak_take": ("slabyy_zahod", "mda"),
    "dismissal": ("idi_lesom", "zavali_varezhku"),
    "so_what": ("nu_i_che", "yasno"),
    "aura_loss": ("minus_aura",),
    "approval": ("yayceslav_odobryaet", "horosh", "plus_aura"),
    "agreement": ("baza", "yayceslav_odobryaet"),
    "dry_reply": ("mda", "yasno"),
    "fail": ("ne_vyvez", "eto_fiasko_bratan", "minus_aura"),
    "outplayed": ("pereigral_i_unichtozhil", "horosh"),
    "proof": ("gde_prufy",),
    "lets_go": ("za_dvizh", "plus_aura"),
    "alarm": ("kod_krasnyy", "eto_fiasko_bratan"),
    "respect_f": ("f",),
    "aura_gain": ("plus_aura", "horosh"),
    "fiasko": ("eto_fiasko_bratan", "ne_vyvez"),
    "salt": ("obtekay", "krinzh"),
    "fight": ("shcha_razebu", "ne_bazar"),
    "no_talk": ("ne_bazar", "zavali_varezhku"),
    "skill_issue": ("skill_issue", "slabyy_zahod"),
    "friday": ("pyatnitsa",),
    "skoof": ("tyazhelyy_skuf",),
    "ancestor": ("slava_prashchuru",),
    "money": ("derzhi_nishchiy",),
    "cringe": ("krinzh", "minus_aura"),
}

# Chance is evaluated only after an event has been found and all cooldowns
# passed. Stickers should be rarer than emoji reactions.
EVENT_CHANCE: Final[dict[str, float]] = {
    "direct_ping": 0.24,
    "shut_up": 0.22,
    "ramble": 0.14,
    "weak_take": 0.16,
    "dismissal": 0.20,
    "so_what": 0.14,
    "aura_loss": 0.24,
    "approval": 0.18,
    "agreement": 0.17,
    "dry_reply": 0.10,
    "fail": 0.20,
    "outplayed": 0.22,
    "proof": 0.22,
    "lets_go": 0.18,
    "alarm": 0.20,
    "respect_f": 0.22,
    "aura_gain": 0.20,
    "fiasko": 0.20,
    "salt": 0.18,
    "fight": 0.18,
    "no_talk": 0.20,
    "skill_issue": 0.20,
    "friday": 0.24,
    "skoof": 0.22,
    "ancestor": 0.24,
    "money": 0.20,
    "cringe": 0.22,
}

_SERIOUS_RE = re.compile(
    r"\b(?:суицид|самоубий|умер|смерт|рак|онколог|инсульт|инфаркт|"
    r"беремен|насили|полици|суд|адвокат|лекарств|диагноз|врач|больниц)\w*\b",
    re.IGNORECASE,
)

_EVENT_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("proof", re.compile(r"\b(?:пруф\w*|доказ\w*|источник\w*|ссылк\w*|откуда\s+(?:инфа|информация))\b", re.I)),
    ("friday", re.compile(r"\b(?:пятниц\w*|бухать|бухич|нахуяр\w*|напиться|пивк\w*|пив[оа])\b", re.I)),
    ("ancestor", re.compile(r"\b(?:пращур\w*|ящер\w*|гойда|древн(?:ий|его)\s+рус)\b", re.I)),
    ("money", re.compile(r"\b(?:нищ\w*|денег\s+нет|без\s+денег|дорого|зарплат\w*|скидк\w*|полтинник|бабк\w*)\b", re.I)),
    ("cringe", re.compile(r"\b(?:кринж\w*|cringe|стыдоба|позорищ\w*|испанский\s+стыд)\b", re.I)),
    ("skill_issue", re.compile(r"\b(?:skill\s*issue|скилл\s*ищ\w*|нуб\w*|руки\s+из\s+жопы|не\s+умеешь\w*)\b", re.I)),
    ("aura_loss", re.compile(r"\b(?:минус\s+аура|ауру\s+потерял|аура\s+в\s+минус)\b", re.I)),
    ("aura_gain", re.compile(r"\b(?:плюс\s+аура|аура\s+в\s+плюс)\b", re.I)),
    ("outplayed", re.compile(r"\b(?:переиграл\w*|уничтожил\w*|разъебал\w*|разн[её]с\w*|выиграл\s+спор)\b", re.I)),
    ("shut_up", re.compile(r"\b(?:заткнись|завали\s+(?:ебало|варежку)|молчи|не\s+пизди|не\s+базарь)\b", re.I)),
    ("dismissal", re.compile(r"\b(?:отъебись|отвали|иди\s+нахуй|пош[её]л\s+нахуй|иди\s+лесом)\b", re.I)),
    ("fight", re.compile(r"\b(?:щас|сейчас)\s+(?:разъебу|вынесу|уничтожу|ебну)\b", re.I)),
    ("alarm", re.compile(r"\b(?:код\s+красный|срочно|авария|горит|всё\s+сломалось|все\s+сломалось)\b", re.I)),
    ("respect_f", re.compile(r"(?:\brip\b|\bpress\s+f\b|\bf\s+в\s+чат\b|земля\s+пухом)", re.I)),
    ("fiasko", re.compile(r"\b(?:фиаско|факап\w*|провал\w*|обосрал\w*|проебал\w*)\b", re.I)),
    ("fail", re.compile(r"\b(?:не\s+вывез\w*|слил\w*|слился|не\s+получилось|не\s+смог\w*)\b", re.I)),
    ("salt", re.compile(r"\b(?:обтекай|сгорел\w*|бомбанул\w*|подгорел\w*)\b", re.I)),
    ("agreement", re.compile(r"\b(?:база|based|согласен|согласна|верно|точно|факт)\b", re.I)),
    ("approval", re.compile(r"\b(?:хорош|заебись|заебато|красавчик|огонь|топчик|супер)\b", re.I)),
    ("lets_go", re.compile(r"\b(?:за\s+движ|погнали|го\s+(?:туда|делать|играть|бухать)|движуха|вписка)\b", re.I)),
    ("weak_take", re.compile(r"\b(?:слабый\s+заход|не\s+убедил\w*|аргумент\s+(?:хуйня|слабый)|чушь)\b", re.I)),
    ("so_what", re.compile(r"^(?:ну\s+и\s+ч[её]\??|и\??|и\s+что\??|дальше\??)$", re.I)),
    ("dry_reply", re.compile(r"^(?:мда+|ясно|понятно|ага|ну\s+да|ок(?:ей)?)\.?$", re.I)),
    ("skoof", re.compile(r"\b(?:скуф\w*|скуфидон\w*)\b", re.I)),
)

_DIRECT_ADDRESS_RE = re.compile(
    r"^\s*(?:эй[,.!]?\s*)?(?:яйцеслав\w*|бобр\w*|курва|бот|помощник)\b",
    re.IGNORECASE,
)


def is_serious_text(text: str) -> bool:
    return bool(_SERIOUS_RE.search(text or ""))


def is_direct_address(text: str, bot_username: str = "") -> bool:
    text = text or ""
    if bot_username and f"@{bot_username}".lower() in text.lower():
        return True
    return bool(_DIRECT_ADDRESS_RE.search(text))


def detect_event(text: str, *, direct: bool = False) -> str | None:
    """Return the first strong sticker event found in a message."""

    stripped = (text or "").strip()
    if not stripped or is_serious_text(stripped):
        return None

    if direct and len(stripped.split()) <= 4:
        return "direct_ping"

    # Very long chat walls get a separate low-frequency sticker slot.
    if len(stripped) >= 650:
        return "ramble"

    for event, pattern in _EVENT_PATTERNS:
        if pattern.search(stripped):
            return event

    return None


def choose_sticker_key(event: str, rng: random.Random | None = None) -> str | None:
    options = EVENT_STICKERS.get(event)
    if not options:
        return None
    chooser = rng or random
    return chooser.choice(options)


def event_chance(event: str) -> float:
    return float(EVENT_CHANCE.get(event, 0.12))


def validate_map() -> None:
    known = set(STICKER_ORDER)
    if set(STICKER_LABELS) != known:
        raise RuntimeError("STICKER_LABELS and STICKER_ORDER are out of sync")
    unknown = {
        key
        for options in EVENT_STICKERS.values()
        for key in options
        if key not in known
    }
    if unknown:
        raise RuntimeError(f"Unknown sticker keys in EVENT_STICKERS: {sorted(unknown)}")


validate_map()
