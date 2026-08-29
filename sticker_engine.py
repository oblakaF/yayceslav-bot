"""Context map for Yayceslav's official Telegram sticker pack.

The pack order in STICKER_ORDER MUST match Telegram exactly. Telegram runtime
maps pack positions to semantic keys, while this module decides what a sticker
means and when it is appropriate. Foreign sticker packs are handled elsewhere
and never enter this map.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
import re
from typing import Final

STICKER_SET_NAME: Final = "yayceslav_stickers"
STICKER_PACK_URL: Final = "https://t.me/addstickers/yayceslav_stickers"

# Unsolicited background stickers are deliberately rare. 2% is a hard ceiling
# after a strong event match; aggressive stickers are configured even lower.
BACKGROUND_STICKER_CHANCE_CAP: Final = 0.02

# Final live Telegram order, 18 Aug 2026: 37 stickers.
STICKER_ORDER: Final[tuple[str, ...]] = (
    "ty_po_moemu_pereputal",
    "14_minut_blyat",
    "ty_dumal_zvezdnyy_lord",
    "goyda_mars_nash",
    "vremya_zavalit_ebalo",
    "tyazhelo_tyazhelo",
    "nadel_tebya_na_suk",
    "doebu_do_ideala",
    "idi_nahui",
    "che_nado",
    "zavali_varezhku",
    "po_delu_govori",
    "slabyy_zahod",
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
    "ty_po_moemu_pereputal": "ТЫ ПО-МОЕМУ ПЕРЕПУТАЛ",
    "14_minut_blyat": "14 МИНУТ, БЛЯТЬ",
    "ty_dumal_zvezdnyy_lord": "ТЫ ДУМАЛ, ТЫ ЗВЁЗДНЫЙ ЛОРД?",
    "goyda_mars_nash": "ГОЙДА!!! МАРС НАШ",
    "vremya_zavalit_ebalo": "ВРЕМЯ ЗАВАЛИТЬ ЕБАЛО",
    "tyazhelo_tyazhelo": "ТЯЖЕЛО... ТЯЖЕЛО",
    "nadel_tebya_na_suk": "Я НАДЕЛ ТЕБЯ НА СУК",
    "doebu_do_ideala": "ДОЕБУ ДО ИДЕАЛА",
    "idi_nahui": "ИДИ НА ХУЙ!",
    "che_nado": "ЧЁ НАДО?",
    "zavali_varezhku": "ЗАВАЛИ ВАРЕЖКУ",
    "po_delu_govori": "ПО ДЕЛУ ГОВОРИ",
    "slabyy_zahod": "СЛАБЫЙ ЗАХОД",
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
    "skill_issue": "СКИЛЛ ИШЬЮ",
    "pyatnitsa": "ПЯТНИЦА? ПОРА НАХУЯРИТЬСЯ",
    "tyazhelyy_skuf": "ТЯЖЁЛЫЙ СКУФ",
    "slava_prashchuru": "СЛАВА ПРАЩУРУ / СМЕРТЬ ЯЩЕРУ",
    "derzhi_nishchiy": "ДЕРЖИ, НИЩИЙ",
    "krinzh": "КРИНЖ",
}


@dataclass(frozen=True)
class StickerMeaning:
    intent: str
    strength: int
    meaning: str


# Human-readable semantic contract. This is deliberately exhaustive so future
# additions cannot silently become "random pictures" with no defined meaning.
STICKER_SEMANTICS: Final[dict[str, StickerMeaning]] = {
    "ty_po_moemu_pereputal": StickerMeaning("correction", 1, "Confident factual/role mix-up; the person has clearly confused things."),
    "14_minut_blyat": StickerMeaning("waiting", 1, "Long wait, delay, somebody or something is taking forever."),
    "ty_dumal_zvezdnyy_lord": StickerMeaning("swagger", 1, "Tease excessive swagger, heroic posing or inflated self-importance."),
    "goyda_mars_nash": StickerMeaning("epic_victory", 1, "Absurdly epic celebration, team win or over-the-top triumph."),
    "vremya_zavalit_ebalo": StickerMeaning("shut_up", 3, "Conversation has become repetitive/noisy and it is time to stop talking."),
    "tyazhelo_tyazhelo": StickerMeaning("fatigue", 1, "Comic exhaustion, difficult routine, dragged-out non-serious situation."),
    "nadel_tebya_na_suk": StickerMeaning("self_own", 2, "Opponent trapped himself or had his own argument turned back on him."),
    "doebu_do_ideala": StickerMeaning("perfection", 1, "Keep polishing, fixing and refining until the work is perfect."),
    "idi_nahui": StickerMeaning("hard_dismissal", 3, "Hard dismissal after explicit hostility/provocation; semantic replacement for old ИДИ ЛЕСОМ."),
    "che_nado": StickerMeaning("direct_ping", 1, "Short rough greeting to a contextless direct ping."),
    "zavali_varezhku": StickerMeaning("shut_up", 2, "Short sharp request to stop talking in banter/conflict."),
    "po_delu_govori": StickerMeaning("focus", 1, "Too much water: ask for the point."),
    "slabyy_zahod": StickerMeaning("weak_take", 1, "Weak joke, weak jab or unconvincing opening."),
    "nu_i_che": StickerMeaning("so_what", 1, "The statement is unimpressive or does not establish anything."),
    "minus_aura": StickerMeaning("aura_loss", 1, "Cringe or reputational loss in playful slang."),
    "yayceslav_odobryaet": StickerMeaning("approval", 1, "Strong general approval."),
    "baza": StickerMeaning("agreement", 1, "Straightforward agreement with a solid take."),
    "mda": StickerMeaning("dry_disappointment", 1, "Dry disappointment or awkward disbelief."),
    "yasno": StickerMeaning("dry_close", 1, "Dry acknowledgement/closure."),
    "ne_vyvez": StickerMeaning("personal_fail", 1, "A person could not handle the task, argument or pressure."),
    "pereigral_i_unichtozhil": StickerMeaning("outplayed", 2, "Clear dominant win in a joke, argument or game."),
    "horosh": StickerMeaning("praise", 1, "Concise praise for a good move or answer."),
    "gde_prufy": StickerMeaning("proof", 1, "Request evidence/source for an unsupported claim."),
    "za_dvizh": StickerMeaning("lets_go", 1, "Support an activity, plan or energetic proposal."),
    "kod_krasnyy": StickerMeaning("alarm", 1, "Critical bug, emergency-like failure or everything is on fire."),
    "f": StickerMeaning("respect_f", 1, "Meme acknowledgement of a non-serious loss/failure/end."),
    "plus_aura": StickerMeaning("aura_gain", 1, "Playful respect/reputation gain."),
    "eto_fiasko_bratan": StickerMeaning("fiasko", 1, "The situation itself ended in an obvious failure."),
    "obtekay": StickerMeaning("salt", 2, "After a clean hit/outplay: opponent is left to absorb it."),
    "shcha_razebu": StickerMeaning("fight", 2, "Pre-flight sticker before a hard roast or teardown."),
    "ne_bazar": StickerMeaning("no_talk", 2, "Too much bravado/noise; stop the empty talk."),
    "skill_issue": StickerMeaning("skill_issue", 1, "Problem is skill/competence rather than circumstances."),
    "pyatnitsa": StickerMeaning("friday", 1, "Friday/party/drinks banter only."),
    "tyazhelyy_skuf": StickerMeaning("skoof", 1, "Heavy old-guy/skoof domestic vibe."),
    "slava_prashchuru": StickerMeaning("ancestor", 1, "Absurd pseudo-Slavic/pra-shchur/lizard meme universe."),
    "derzhi_nishchiy": StickerMeaning("money", 1, "Playful handing over of a resource/file/money-like thing."),
    "krinzh": StickerMeaning("cringe", 1, "Plain cringe/second-hand embarrassment."),
}

# Event -> semantically valid outputs. Strong insults are isolated into strong
# events so a generic negative message can never randomly escalate to them.
EVENT_STICKERS: Final[dict[str, tuple[str, ...]]] = {
    "direct_ping": ("che_nado", "nu_i_che"),
    "confusion": ("ty_po_moemu_pereputal", "gde_prufy"),
    "waiting": ("14_minut_blyat", "tyazhelo_tyazhelo"),
    "swagger": ("ty_dumal_zvezdnyy_lord", "minus_aura"),
    "epic_victory": ("goyda_mars_nash", "pereigral_i_unichtozhil", "plus_aura"),
    "shut_up_escalated": ("vremya_zavalit_ebalo",),
    "fatigue": ("tyazhelo_tyazhelo", "mda"),
    "self_own": ("nadel_tebya_na_suk", "pereigral_i_unichtozhil", "obtekay"),
    "perfection": ("doebu_do_ideala", "horosh"),
    "hard_dismissal": ("idi_nahui",),
    "shut_up": ("zavali_varezhku", "ne_bazar"),
    "ramble": ("po_delu_govori", "mda"),
    "weak_take": ("slabyy_zahod", "mda"),
    "so_what": ("nu_i_che", "yasno"),
    "aura_loss": ("minus_aura",),
    "approval": ("yayceslav_odobryaet", "horosh", "plus_aura"),
    "agreement": ("baza", "yayceslav_odobryaet"),
    "dry_reply": ("mda", "yasno"),
    "fail": ("ne_vyvez", "eto_fiasko_bratan", "minus_aura"),
    "outplayed": ("pereigral_i_unichtozhil", "nadel_tebya_na_suk", "horosh"),
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

# These are effective pre-cap weights after a strong semantic match. Aggressive
# stickers are much rarer than neutral reactions even before cooldowns.
EVENT_CHANCE: Final[dict[str, float]] = {
    "direct_ping": 0.02,
    "confusion": 0.02,
    "waiting": 0.02,
    "swagger": 0.015,
    "epic_victory": 0.02,
    "shut_up_escalated": 0.008,
    "fatigue": 0.02,
    "self_own": 0.015,
    "perfection": 0.02,
    "hard_dismissal": 0.006,
    "shut_up": 0.01,
    "ramble": 0.015,
    "weak_take": 0.02,
    "so_what": 0.02,
    "aura_loss": 0.02,
    "approval": 0.02,
    "agreement": 0.02,
    "dry_reply": 0.015,
    "fail": 0.02,
    "outplayed": 0.015,
    "proof": 0.02,
    "lets_go": 0.02,
    "alarm": 0.02,
    "respect_f": 0.015,
    "aura_gain": 0.02,
    "fiasko": 0.02,
    "salt": 0.012,
    "fight": 0.01,
    "no_talk": 0.01,
    "skill_issue": 0.02,
    "friday": 0.02,
    "skoof": 0.02,
    "ancestor": 0.02,
    "money": 0.015,
    "cringe": 0.02,
}

_SERIOUS_RE = re.compile(
    r"\b(?:суицид|самоубий|умер|смерт|похорон|рак|онколог|инсульт|инфаркт|"
    r"беремен|насили|полици|суд|адвокат|лекарств|диагноз|врач|больниц|"
    r"авари[яи]|травм|кровотеч|скорую|реанимац)\w*\b",
    re.IGNORECASE,
)

_EVENT_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("proof", re.compile(r"\b(?:пруф\w*|доказ\w*|источник\w*|ссылк\w*|откуда\s+(?:инфа|информация))\b", re.I)),
    ("waiting", re.compile(r"\b(?:сколько\s+(?:можно\s+)?ждать|долго\s+ещ[её]|когда\s+(?:уже|наконец)|задерж\w*|опазд\w*|жду\s+(?:уже\s+)?\d+|\d+\s+минут\s+жд)\b", re.I)),
    ("perfection", re.compile(r"\b(?:до\s+идеала|дошлиф\w*|допил\w*|доработ\w*|перфекциони\w*|ещ[её]\s+чуть-чуть\s+(?:поправ|додел))\b", re.I)),
    ("fatigue", re.compile(r"\b(?:тяжело|заебал(?:ся|ась|ись)|устал(?:а|и)?|сил\s+нет|задолбал(?:о|ся|ась)?)\b", re.I)),
    ("swagger", re.compile(r"\b(?:зв[её]здный\s+лорд|король\s+мира|я\s+легенда|я\s+лучший|бог\s+(?:этой|этого|чата|игры)|главный\s+герой)\b", re.I)),
    ("epic_victory", re.compile(r"\b(?:марс\s+наш|гойда|мы\s+(?:взяли|победили|выиграли)|победа|разъебали\s+(?:их|всех)|затащили)\b", re.I)),
    ("self_own", re.compile(r"\b(?:сам\s+себя\s+(?:подловил|закопал|опроверг|переиграл)|своим\s+же\s+аргументом|против\s+себя\s+же|сам\s+себе\s+противореч)\b", re.I)),
    ("confusion", re.compile(r"\b(?:ты\s+(?:по[- ]?моему\s+)?перепутал|вы\s+перепутали|путаешь|перепутал\s+(?:факты|роли|причину)|не\s+то\s+с\s+тем)\b", re.I)),
    ("friday", re.compile(r"\b(?:пятниц\w*|бухать|бухич|нахуяр\w*|напиться|пивк\w*|пив[оа])\b", re.I)),
    ("ancestor", re.compile(r"\b(?:пращур\w*|ящер\w*|древн(?:ий|его)\s+рус)\b", re.I)),
    ("money", re.compile(r"\b(?:нищ\w*|денег\s+нет|без\s+денег|дорого|зарплат\w*|скидк\w*|полтинник|бабк\w*)\b", re.I)),
    ("cringe", re.compile(r"\b(?:кринж\w*|cringe|стыдоба|позорищ\w*|испанский\s+стыд)\b", re.I)),
    ("skill_issue", re.compile(r"\b(?:skill\s*issue|скилл\s*ищ\w*|нуб\w*|руки\s+из\s+жопы|не\s+умеешь\w*)\b", re.I)),
    ("aura_loss", re.compile(r"\b(?:минус\s+аура|ауру\s+потерял|аура\s+в\s+минус)\b", re.I)),
    ("aura_gain", re.compile(r"\b(?:плюс\s+аура|аура\s+в\s+плюс)\b", re.I)),
    ("outplayed", re.compile(r"\b(?:переиграл\w*|уничтожил\w*|разъебал\w*|разн[её]с\w*|выиграл\s+спор)\b", re.I)),
    ("shut_up_escalated", re.compile(r"\b(?:сколько\s+можно\s+пиздеть|хватит\s+уже\s+(?:пиздеть|говорить|душнить)|время\s+завалить\s+ебало|заебал\s+повторять)\b", re.I)),
    ("hard_dismissal", re.compile(r"\b(?:иди\s+на\s*хуй|иди\s+нахуй|пош[её]л\s+на\s*хуй|пош[её]л\s+нахуй|отъебись|иди\s+лесом)\b", re.I)),
    ("shut_up", re.compile(r"\b(?:заткнись|завали\s+(?:ебало|варежку)|молчи|не\s+пизди)\b", re.I)),
    ("fight", re.compile(r"\b(?:щас|сейчас)\s+(?:разъебу|вынесу|уничтожу|ебну)\b", re.I)),
    ("alarm", re.compile(r"\b(?:код\s+красный|срочно|всё\s+сломалось|все\s+сломалось|сервер\s+лежит|прод\s+лежит|всё\s+горит)\b", re.I)),
    ("respect_f", re.compile(r"(?:\brip\b|\bpress\s+f\b|\bf\s+в\s+чат\b)", re.I)),
    ("fiasko", re.compile(r"\b(?:фиаско|факап\w*|провал\w*|обосрал\w*|проебал\w*)\b", re.I)),
    ("fail", re.compile(r"\b(?:не\s+вывез\w*|слил\w*|слился|не\s+получилось|не\s+смог\w*)\b", re.I)),
    ("salt", re.compile(r"\b(?:обтекай|сгорел\w*|бомбанул\w*|подгорел\w*)\b", re.I)),
    ("agreement", re.compile(r"\b(?:база|based|согласен|согласна|верно|точно|факт)\b", re.I)),
    ("approval", re.compile(r"\b(?:хорош|заебись|заебато|красавчик|огонь|топчик|супер)\b", re.I)),
    ("lets_go", re.compile(r"\b(?:за\s+движ|погнали|го\s+(?:туда|делать|играть|бухать)|движуха|вписка)\b", re.I)),
    ("weak_take", re.compile(r"\b(?:слабый\s+заход|не\s+убедил\w*|аргумент\s+(?:хуйня|слабый)|чушь)\b", re.I)),
    ("no_talk", re.compile(r"\b(?:не\s+базарь|понтов\s+много|хватит\s+понтов)\b", re.I)),
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
    """Return the first strong semantic sticker event found in a message."""
    stripped = (text or "").strip()
    if not stripped or is_serious_text(stripped):
        return None

    if len(stripped) >= 650:
        return "ramble"

    # Strong semantics win over a generic direct ping.
    for event, pattern in _EVENT_PATTERNS:
        if pattern.search(stripped):
            return event

    if direct and len(stripped.split()) <= 4:
        return "direct_ping"
    return None


def choose_sticker_key(event: str, rng: random.Random | None = None) -> str | None:
    options = EVENT_STICKERS.get(event)
    if not options:
        return None
    chooser = rng or random
    return chooser.choice(options)


def event_chance(event: str) -> float:
    """Return effective unsolicited sticker chance, never above 2%."""
    raw = float(EVENT_CHANCE.get(event, 0.0))
    return max(0.0, min(BACKGROUND_STICKER_CHANCE_CAP, raw))


REPUTATION_COLD_STICKER_THRESHOLD = -26
REPUTATION_WARM_STICKER_THRESHOLD = 26


def reputation_sticker_chance(event: str, reputation_score: int | None) -> float:
    """A playful background sticker leans toward people the bot likes.

    Still capped at BACKGROUND_STICKER_CHANCE_CAP -- reputation nudges the
    chance, it never turns a rare gesture into a common one.
    """
    base = event_chance(event)
    if reputation_score is None:
        return base
    score = int(reputation_score)
    if score <= REPUTATION_COLD_STICKER_THRESHOLD:
        multiplier = 0.4
    elif score >= REPUTATION_WARM_STICKER_THRESHOLD:
        multiplier = 1.5
    else:
        multiplier = 1.0
    return max(0.0, min(BACKGROUND_STICKER_CHANCE_CAP, base * multiplier))


def validate_map() -> None:
    known = set(STICKER_ORDER)
    if len(STICKER_ORDER) != 37 or len(known) != 37:
        raise RuntimeError("Final Yayceslav sticker pack must contain 37 unique keys")
    if set(STICKER_LABELS) != known:
        raise RuntimeError("STICKER_LABELS and STICKER_ORDER are out of sync")
    if set(STICKER_SEMANTICS) != known:
        raise RuntimeError("STICKER_SEMANTICS must describe every sticker exactly once")

    unknown = {
        key
        for options in EVENT_STICKERS.values()
        for key in options
        if key not in known
    }
    if unknown:
        raise RuntimeError(f"Unknown sticker keys in EVENT_STICKERS: {sorted(unknown)}")

    if set(EVENT_CHANCE) != set(EVENT_STICKERS):
        raise RuntimeError("EVENT_CHANCE and EVENT_STICKERS are out of sync")
    if not (0.0 <= BACKGROUND_STICKER_CHANCE_CAP <= 0.05):
        raise RuntimeError("Background sticker cap is unexpectedly high")

    aggressive = {key for key, item in STICKER_SEMANTICS.items() if item.strength >= 3}
    if aggressive != {"vremya_zavalit_ebalo", "idi_nahui"}:
        raise RuntimeError("Aggressive sticker classification changed unexpectedly")


validate_map()
