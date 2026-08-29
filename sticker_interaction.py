"""Pure interaction rules for Yayceslav's own Telegram sticker pack."""

from __future__ import annotations

import random
import re
from typing import Final

import sticker_engine

# Direct questions: this is a MAXIMUM slot, not a promise to send a sticker.
QUESTION_STICKER_REPLY_CHANCE: Final = 0.05

# Incoming own-pack stickers: 50/50 between a semantic sticker comeback and
# a short text comeback. If there is no genuinely good sticker comeback, text
# wins even when the 50% sticker branch was drawn.
OWN_STICKER_REPLY_CHANCE: Final = 0.50

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

# Incoming sticker -> ONLY genuinely natural sticker counter-replies.
# Empty tuple is intentional: when there is no clean visual counterargument,
# the bot answers with text instead of forcing a random sticker.
OWN_STICKER_COMEBACKS: Final[dict[str, tuple[str, ...]]] = {
    "ty_po_moemu_pereputal": ("gde_prufy", "mda"),
    "14_minut_blyat": ("tyazhelo_tyazhelo",),
    "ty_dumal_zvezdnyy_lord": ("minus_aura", "krinzh"),
    "goyda_mars_nash": ("za_dvizh", "plus_aura"),
    "vremya_zavalit_ebalo": ("ne_bazar", "idi_nahui"),
    "tyazhelo_tyazhelo": (),
    "nadel_tebya_na_suk": ("pereigral_i_unichtozhil", "obtekay"),
    "doebu_do_ideala": ("horosh", "plus_aura"),
    "idi_nahui": ("ne_bazar", "obtekay", "zavali_varezhku"),
    "che_nado": ("po_delu_govori", "nu_i_che"),
    "zavali_varezhku": ("obtekay", "ne_bazar", "idi_nahui"),
    "po_delu_govori": (),
    "slabyy_zahod": ("krinzh", "obtekay"),
    "nu_i_che": ("yasno", "mda"),
    "minus_aura": ("plus_aura",),
    "yayceslav_odobryaet": ("baza", "horosh"),
    "baza": ("yayceslav_odobryaet", "horosh"),
    "mda": ("yasno",),
    "yasno": ("mda",),
    "ne_vyvez": ("ty_po_moemu_pereputal", "obtekay"),
    "pereigral_i_unichtozhil": ("ty_po_moemu_pereputal", "gde_prufy", "nadel_tebya_na_suk"),
    "horosh": ("plus_aura", "yayceslav_odobryaet"),
    "gde_prufy": (),
    "za_dvizh": ("horosh", "plus_aura"),
    "kod_krasnyy": ("f", "eto_fiasko_bratan"),
    "f": (),
    "plus_aura": ("yayceslav_odobryaet", "horosh"),
    "eto_fiasko_bratan": ("f", "ne_vyvez"),
    "obtekay": ("skill_issue", "mda"),
    "shcha_razebu": ("slabyy_zahod", "ne_bazar"),
    "ne_bazar": ("zavali_varezhku", "obtekay"),
    "skill_issue": ("obtekay", "slabyy_zahod"),
    "pyatnitsa": ("za_dvizh", "horosh"),
    "tyazhelyy_skuf": ("krinzh", "baza"),
    "slava_prashchuru": ("goyda_mars_nash", "yayceslav_odobryaet"),
    "derzhi_nishchiy": ("horosh", "plus_aura"),
    "krinzh": ("minus_aura", "mda"),
}

# Short human-style text responses for the other 50% and for semantic fallback.
# These are deliberately concise and keyed to the sticker's actual meaning.
OWN_STICKER_TEXT_REPLIES: Final[dict[str, tuple[str, ...]]] = {
    "ty_po_moemu_pereputal": ("Так поправь, где именно.", "Пруфы на стол, сейчас сверим.", "Уверенно сказал. Теперь докажи."),
    "14_minut_blyat": ("Терпение, маршрутка бытия уже где-то рядом.", "Четырнадцать? Уже можно злиться.", "Да, ожидание пошло по пизде."),
    "ty_dumal_zvezdnyy_lord": ("Пафоса убавь, лорд.", "Шлем сними, тебя узнали.", "До галактики пока далековато."),
    "goyda_mars_nash": ("Победа зафиксирована. Марс держим.", "Вот это уже движ.", "Империя одобряет."),
    "vremya_zavalit_ebalo": ("Самое время начать с себя.", "Сильная заявка на тишину.", "Принято. Но командовать тут не тебе."),
    "tyazhelo_tyazhelo": ("Тяжело. Но пока тащим.", "Жизнь опять включила хардмод.", "Понимаю. Ситуация штатно тяжёлая."),
    "nadel_tebya_na_suk": ("Сначала проверь, не сидишь ли сам рядом.", "Красиво придумал. Теперь слезай.", "Самоподстава засчитана, вопрос только чья."),
    "doebu_do_ideala": ("Вот это правильный подход.", "Ещё полмиллиметра — и идеально.", "Не трогай его. Он дошлифует."),
    "idi_nahui": ("Сам иди.", "Отъебись, навигатор.", "Маршрут понятен. Следуй первым."),
    "che_nado": ("По делу пришёл или просто дверью хлопнул?", "Говори, чего хотел.", "Ну? Я слушаю."),
    "zavali_varezhku": ("Свою сначала прикрой.", "Не командуй тут.", "Варежка на месте, переживёшь."),
    "po_delu_govori": ("Так говори по делу.", "Я слушаю. Где дело?", "Убери воду — оставь мысль."),
    "slabyy_zahod": ("Согласен, попробуй ещё раз.", "Разминка не засчитана.", "Панч не долетел."),
    "nu_i_che": ("И всё.", "Вот именно: ну и чё?", "Продолжение будет или это финал?"),
    "minus_aura": ("Компенсирую. Плюс аура.", "Себе запиши.", "Аура восстановлена, не переживай."),
    "yayceslav_odobryaet": ("Одобрение взаимно.", "Редкий случай: согласен.", "Вот теперь по-людски."),
    "baza": ("База подтверждена.", "Тут спорить не с чем.", "Зафиксировали."),
    "mda": ("Исчерпывающий анализ.", "Даже добавить нечего.", "Мда так мда."),
    "yasno": ("Ну и отлично.", "Раз ясно — живём дальше.", "Принято."),
    "ne_vyvez": ("Рано празднуешь.", "Пересчёт ещё не закончен.", "Ты сначала финиш покажи."),
    "pereigral_i_unichtozhil": ("В своих фантазиях — безусловно.", "Протокол победы где?", "Празднуй, пока пересчёт не начался."),
    "horosh": ("Сам хорош.", "Засчитано.", "Вот это по делу."),
    "gde_prufy": ("Правильный вопрос. Где они?", "Без пруфов это фольклор.", "Источник в студию."),
    "za_dvizh": ("За нормальный — всегда.", "Движ принят.", "Погнали."),
    "kod_krasnyy": ("Кто опять прод уронил?", "Тревога принята. Где горит?", "Красный так красный. Чиним."),
    "f": ("F принят.", "Помянули и поехали дальше.", "Минуту молчания закончили."),
    "plus_aura": ("Аура принята.", "Верну с процентами.", "Вот это другое дело."),
    "eto_fiasko_bratan": ("Фиаско принято к сведению.", "Зато эффектно.", "План был хороший. Секунды три."),
    "obtekay": ("Не захлебнись собственной волной.", "Обтекать будешь после пруфов.", "Рано воду включил."),
    "shcha_razebu": ("Начинай, зрители собрались.", "Давай, удиви.", "Главное сам не разъебись."),
    "ne_bazar": ("Базара и не было.", "Тогда факты давай.", "Согласен: меньше слов."),
    "skill_issue": ("Диагноз удобный. Пруфы будут?", "Скилл проверим на практике.", "Главное, чтоб не твой."),
    "pyatnitsa": ("Пятница подтверждена протоколом.", "Вот теперь аргумент весомый.", "Режим пятницы активирован."),
    "tyazhelyy_skuf": ("Тяжёлый — не значит бесполезный.", "Скуф, зато сертифицированный.", "Опыт весит много."),
    "slava_prashchuru": ("Пращур услышал.", "Ящеры занервничали.", "Летопись пополнена."),
    "derzhi_nishchiy": ("Благотворительность засчитана.", "Щедро. Почти подозрительно.", "Принял, богач."),
    "krinzh": ("Кринж зафиксирован.", "Да, неловкость плотная.", "Согласен. Это было больно смотреть."),
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
    """Return a semantically valid sticker or None for a normal text answer."""
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
    """Choose only a semantically strong visual counter-reply."""
    options = OWN_STICKER_COMEBACKS.get(incoming_sticker_key, ())
    if not options:
        return None
    return rng.choice(options)


def choose_own_pack_text_reply(
    incoming_sticker_key: str,
    *,
    rng=random,
) -> str | None:
    options = OWN_STICKER_TEXT_REPLIES.get(incoming_sticker_key, ())
    if not options:
        return None
    return rng.choice(options)


def validate_interaction_map() -> None:
    known = set(sticker_engine.STICKER_ORDER)

    assert QUESTION_STICKER_REPLY_CHANCE == 0.05
    assert OWN_STICKER_REPLY_CHANCE == 0.50
    assert set(OWN_STICKER_COMEBACKS) == known
    assert set(OWN_STICKER_TEXT_REPLIES) == known

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

    hard = {"idi_nahui", "vremya_zavalit_ebalo"}
    question_outputs = {
        key for replies in QUESTION_EVENT_STICKERS.values() for key in replies
    }
    if hard & question_outputs:
        raise RuntimeError("Hard hostile stickers leaked into direct-question pool")

    # Regression for the bad pairings seen in live chat.
    if "baza" in OWN_STICKER_COMEBACKS["po_delu_govori"]:
        raise RuntimeError("ПО ДЕЛУ ГОВОРИ must not randomly answer БАЗА")
    if "za_dvizh" in OWN_STICKER_COMEBACKS["pereigral_i_unichtozhil"]:
        raise RuntimeError("ПЕРЕИГРАЛ И УНИЧТОЖИЛ must not randomly answer ЗА ДВИЖ")
    if "plus_aura" not in OWN_STICKER_COMEBACKS["minus_aura"]:
        raise RuntimeError("МИНУС АУРА should have ПЛЮС АУРА as its visual counter")


validate_interaction_map()
