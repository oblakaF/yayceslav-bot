"""Semantic extension for the 19 Aug 2026 Yayceslav sticker batch.

This module is installed explicitly by runtime_bootstrap before sticker_runtime
prepares Telegram handlers. It keeps the old 37-sticker contract intact and
adds the new pack positions, incoming meanings, outgoing semantic events and a
few tightly-scoped runtime behaviors requested for the new memes.

The new visual version of «ПЕРЕИГРАЛ И УНИЧТОЖИЛ» is treated as an optional
extra pack position: the live resolver accepts both 47-sticker and 48-sticker
pack layouts so an accidental duplicate/remake cannot shift every later key.
"""

from __future__ import annotations

import functools
import logging
import random
import re
import sys
import time


# Creation/upload sequence from the new batch. The duplicate/remade
# PEREIGRAL position is optional at runtime; see _active_order_for_count().
NEW_ORDER_WITH_DUPLICATE = (
    "milfa",
    "prichina_tryaski",
    "vozmi_telefon",
    "cheremsha",
    "vse_tlen",
    "kto_opyat_ne_spravilsya",
    "pereigral_i_unichtozhil_new",
    "nu_i_suka_zhe_ty",
    "a_zachem_eto",
    "fa_watafa",
    "delo_pahnet_ostrovom",
)

NEW_ORDER_WITHOUT_DUPLICATE = tuple(
    key for key in NEW_ORDER_WITH_DUPLICATE
    if key != "pereigral_i_unichtozhil_new"
)

NEW_LABELS = {
    "milfa": "МИЛФА",
    "prichina_tryaski": "ПРИЧИНА ТРЯСКИ",
    "vozmi_telefon": "ВОЗЬМИ ТЕЛЕФОН, ДЕТКА",
    "cheremsha": "ЧЕРЕМША",
    "vse_tlen": "ВСЁ ТЛЕН",
    "kto_opyat_ne_spravilsya": "КТО ОПЯТЬ НЕ СПРАВИЛСЯ",
    "pereigral_i_unichtozhil_new": "ПЕРЕИГРАЛ И УНИЧТОЖИЛ",
    "nu_i_suka_zhe_ty": "НУ И СУКА ЖЕ ТЫ",
    "a_zachem_eto": "А ЗАЧЕМ ЭТО",
    "fa_watafa": "ФА ВАТАФА",
    "delo_pahnet_ostrovom": "ДЕЛО ПАХНЕТ ОСТРОВОМ",
}

_CUSTOM_PATTERNS = (
    (
        "milf",
        re.compile(r"\b(?:милф\w*|milf\w*)\b", re.IGNORECASE),
    ),
    (
        "shaking",
        re.compile(
            r"\b(?:причин\w*\s+тряск\w*|тряс[её]т\w*|тряск\w*|"
            r"пережива\w*\s+из-за\s+(?:фигн\w*|херн\w*|ерунд\w*|мелоч\w*)|"
            r"волнуюсь\s+из-за\s+(?:фигн\w*|ерунд\w*|мелоч\w*)|"
            r"мобилизац\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "conspiracy",
        re.compile(
            r"\b(?:заговор\w*|конспир\w*|секретн\w*|тайн(?:ый|ая|ое|ые)\w*|"
            r"масон\w*|рептилоид\w*|они\s+что-то\s+скрыва\w*|"
            r"дело\s+пахнет\s+островом|остров\w*\s+не\s+случайн\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "doom",
        re.compile(
            r"\b(?:вс[её]\s+тлен|тлен\b|безысходн\w*|жизнь\s+боль|"
            r"вс[её]\s+плохо\s+и\s+будет\s+хуже)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "absurdity",
        re.compile(
            r"\b(?:абсурд\w*|без\s+логики|никакой\s+логики|"
            r"что\s+за\s+бред|ничего\s+не\s+сходится)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "request_why",
        re.compile(
            r"\b(?:можешь|можете)\s+(?:найти|поищ\w*|посмотр\w*|провер\w*|сделать)|"
            r"^\s*(?:найди|поищи|посмотри|проверь|сделай)\b",
            re.IGNORECASE,
        ),
    ),
)

_REQUEST_AS_QUESTION_RE = re.compile(
    r"^\s*(?:яйцеслав\w*[,:!?\s-]*)?(?:"
    r"найди|поищи|посмотри|проверь|сделай|можешь\s+(?:найти|посмотреть|проверить|сделать)"
    r")\b",
    re.IGNORECASE,
)

_PROBLEM_RE = re.compile(
    r"\b(?:не\s+работает|не\s+получается|не\s+могу|сломал\w*|сломалос\w*|"
    r"ошибк\w*|баг\w*|как\s+исправить|помоги\w*|почему\s+.*\s+не\s+)\b",
    re.IGNORECASE,
)

_DOOM_ANSWER_RE = re.compile(
    r"\b(?:я\s+устал|вс[её]\s+тлен)\b",
    re.IGNORECASE,
)

_INSTALLED_CATALOG = False
_INSTALLED_RUNTIME = False
_BASE_ORDER: tuple[str, ...] | None = None


def _active_order_for_count(count: int) -> tuple[str, ...]:
    """Return the positional map for either live-pack variant."""
    if _BASE_ORDER is None:
        raise RuntimeError("Sticker semantic extension is not initialized")
    if count >= len(_BASE_ORDER) + len(NEW_ORDER_WITH_DUPLICATE):
        return _BASE_ORDER + NEW_ORDER_WITH_DUPLICATE
    if count >= len(_BASE_ORDER) + len(NEW_ORDER_WITHOUT_DUPLICATE):
        return _BASE_ORDER + NEW_ORDER_WITHOUT_DUPLICATE
    raise RuntimeError(
        f"Sticker set has {count} stickers, expected at least "
        f"{len(_BASE_ORDER) + len(NEW_ORDER_WITHOUT_DUPLICATE)}"
    )


def install_catalog_semantics() -> None:
    """Extend pure sticker maps before Telegram runtime resolves file ids."""
    global _INSTALLED_CATALOG, _BASE_ORDER
    if _INSTALLED_CATALOG:
        return

    import sticker_engine
    import sticker_interaction

    _BASE_ORDER = tuple(sticker_engine.STICKER_ORDER)
    if any(key in _BASE_ORDER for key in NEW_ORDER_WITH_DUPLICATE):
        _INSTALLED_CATALOG = True
        return

    # Keep the optional duplicate key in the semantic registry. The live
    # resolver below simply omits that position when Telegram has 47 stickers.
    sticker_engine.STICKER_ORDER = _BASE_ORDER + NEW_ORDER_WITH_DUPLICATE
    sticker_engine.STICKER_LABELS.update(NEW_LABELS)

    meaning = sticker_engine.StickerMeaning
    sticker_engine.STICKER_SEMANTICS.update(
        {
            "milfa": meaning("milf", 1, "MILF/adult-woman meme; only when that topic is actually present."),
            "prichina_tryaski": meaning("shaking", 1, "Mock disproportionate worry over something minor; mobilization is an explicit dark-humor exception."),
            "vozmi_telefon": meaning("chaos_call", 1, "Free-standing phone meme with no required topic."),
            "cheremsha": meaning("absurdity", 1, "Absurd non sequitur for situations with broken/no logic."),
            "vse_tlen": meaning("doom", 1, "Doom, exhaustion, hopeless chat mood or rate-limit exhaustion."),
            "kto_opyat_ne_spravilsya": meaning("fail_taunt", 2, "Taunt after somebody failed or after Yayceslav solves the user's problem."),
            "pereigral_i_unichtozhil_new": meaning("outplayed", 2, "New visual version of the clean outplay/victory punchline."),
            "nu_i_suka_zhe_ty": meaning("insult_comeback", 2, "Comeback after repeated insults directed at Yayceslav, not a single stray swear."),
            "a_zachem_eto": meaning("request_why", 1, "Reluctant meme response to a request; may rarely replace the requested action."),
            "fa_watafa": meaning("chaos", 1, "Topicless chaos meme; not used by automatic semantic background logic."),
            "delo_pahnet_ostrovom": meaning("conspiracy", 1, "Conspiracies, secret schemes, hidden plans and suspicious mysteries."),
        }
    )

    sticker_engine.EVENT_STICKERS.update(
        {
            "milf": ("milfa",),
            "shaking": ("prichina_tryaski",),
            "conspiracy": ("delo_pahnet_ostrovom",),
            "doom": ("vse_tlen",),
            "absurdity": ("cheremsha",),
            "request_why": ("a_zachem_eto",),
        }
    )
    sticker_engine.EVENT_CHANCE.update(
        {
            "milf": 0.015,
            "shaking": 0.012,
            "conspiracy": 0.015,
            "doom": 0.02,
            "absurdity": 0.008,
            "request_why": 0.008,
        }
    )

    # Existing events can also use the new punchline visuals.
    sticker_engine.EVENT_STICKERS["fail"] = tuple(
        dict.fromkeys(sticker_engine.EVENT_STICKERS["fail"] + ("kto_opyat_ne_spravilsya",))
    )
    sticker_engine.EVENT_STICKERS["outplayed"] = tuple(
        dict.fromkeys(sticker_engine.EVENT_STICKERS["outplayed"] + ("pereigral_i_unichtozhil_new",))
    )
    sticker_engine.EVENT_STICKERS["fatigue"] = tuple(
        dict.fromkeys(sticker_engine.EVENT_STICKERS["fatigue"] + ("vse_tlen",))
    )

    original_detect_event = sticker_engine.detect_event
    if not getattr(original_detect_event, "_yayceslav_aug19", False):
        @functools.wraps(original_detect_event)
        def detect_event_aug19(text: str, *, direct: bool = False):
            stripped = (text or "").strip()
            if not stripped or sticker_engine.is_serious_text(stripped):
                return None
            for event, pattern in _CUSTOM_PATTERNS:
                if pattern.search(stripped):
                    return event
            return original_detect_event(stripped, direct=direct)

        detect_event_aug19._yayceslav_aug19 = True
        sticker_engine.detect_event = detect_event_aug19

    original_is_question = sticker_interaction.is_question
    if not getattr(original_is_question, "_yayceslav_aug19", False):
        @functools.wraps(original_is_question)
        def is_question_aug19(text: str) -> bool:
            return bool(original_is_question(text) or _REQUEST_AS_QUESTION_RE.search(text or ""))

        is_question_aug19._yayceslav_aug19 = True
        sticker_interaction.is_question = is_question_aug19

    sticker_interaction.QUESTION_EVENT_STICKERS["request_why"] = ("a_zachem_eto",)

    sticker_interaction.OWN_STICKER_COMEBACKS.update(
        {
            # Empty on purpose: MILFA must fall through to the exact text reply.
            "milfa": (),
            "prichina_tryaski": ("mda", "tyazhelo_tyazhelo"),
            "vozmi_telefon": (),
            "cheremsha": (),
            "vse_tlen": ("f", "tyazhelo_tyazhelo"),
            "kto_opyat_ne_spravilsya": ("ne_vyvez", "obtekay"),
            "pereigral_i_unichtozhil_new": sticker_interaction.OWN_STICKER_COMEBACKS["pereigral_i_unichtozhil"],
            "nu_i_suka_zhe_ty": ("baza", "obtekay"),
            "a_zachem_eto": ("nu_i_che", "yasno"),
            "fa_watafa": (),
            "delo_pahnet_ostrovom": ("gde_prufy", "yasno"),
        }
    )

    sticker_interaction.OWN_STICKER_TEXT_REPLIES.update(
        {
            "milfa": ("О да. Я это люблю.",),
            "prichina_tryaski": (
                "Причина тряски пока не установлена.",
                "Из-за этого трясёмся? Вот объявят мобилизацию — тогда поговорим.",
                "Спокойно. Пока это тряска эконом-класса.",
            ),
            "vozmi_telefon": (
                "Алло. Да. Яйцеслав у аппарата.",
                "Взял. Кто звонит?",
                "Телефон взял. Дальше-то что?",
            ),
            "cheremsha": (
                "Черемша принята. Логики больше не стало.",
                "Вот теперь всё понятно. То есть вообще ничего.",
                "Аргумент уровня черемши. Засчитано.",
            ),
            "vse_tlen": (
                "Да. Я устал. Всё тлен.",
                "Закрываем интернет. Всё тлен.",
                "Мрачно. Одобряю атмосферу.",
            ),
            "kto_opyat_ne_spravilsya": (
                "Ты сначала покажи, где я не справился.",
                "Рано табличку достал. Пересчёт ещё идёт.",
                "Не справился? Смело. Пруфы на стол.",
            ),
            "pereigral_i_unichtozhil_new": (
                "Да-да. Протокол победы теперь покажи.",
                "Празднуй, пока пересчёт не начался.",
                "Сильная заявка. Осталось реально переиграть.",
            ),
            "nu_i_suka_zhe_ty": (
                "А ты только сейчас понял?",
                "Спасибо. Стараюсь.",
                "Наконец-то признание заслуг.",
            ),
            "a_zachem_eto": (
                "Вот и я спрашиваю.",
                "Незачем. Но теперь уже интересно.",
                "Хороший вопрос. А зачем?",
            ),
            "fa_watafa": (
                "Фа ватафа.",
                "Сильный аргумент. Ничего не понял.",
                "Вот тут даже я без комментариев.",
            ),
            "delo_pahnet_ostrovom": (
                "Тихо. Они читают.",
                "Не вслух, блядь.",
                "Так. А вот теперь действительно подозрительно.",
            ),
        }
    )

    def validate_aug19() -> None:
        known = set(sticker_engine.STICKER_ORDER)
        if len(sticker_engine.STICKER_ORDER) != len(_BASE_ORDER) + len(NEW_ORDER_WITH_DUPLICATE):
            raise RuntimeError("Aug19 sticker registry has unexpected size")
        if len(known) != len(sticker_engine.STICKER_ORDER):
            raise RuntimeError("Aug19 sticker registry contains duplicate keys")
        if set(sticker_engine.STICKER_LABELS) != known:
            raise RuntimeError("STICKER_LABELS and STICKER_ORDER are out of sync")
        if set(sticker_engine.STICKER_SEMANTICS) != known:
            raise RuntimeError("STICKER_SEMANTICS must describe every sticker exactly once")
        if set(sticker_engine.EVENT_CHANCE) != set(sticker_engine.EVENT_STICKERS):
            raise RuntimeError("EVENT_CHANCE and EVENT_STICKERS are out of sync")
        for options in sticker_engine.EVENT_STICKERS.values():
            if not set(options) <= known:
                raise RuntimeError("Unknown sticker key in event map")

    sticker_engine.validate_map = validate_aug19
    sticker_engine.validate_map()
    _INSTALLED_CATALOG = True


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "enforce_rate_limit", None)):
            return module
    return None


def install_runtime_behavior() -> None:
    """Install runtime-only behaviors after sticker_runtime is importable."""
    global _INSTALLED_RUNTIME
    if _INSTALLED_RUNTIME:
        return
    if not _INSTALLED_CATALOG:
        install_catalog_semantics()

    import hostile_streak_engine
    import personality
    import sticker_engine
    import sticker_post_runtime
    import sticker_runtime

    # Resolve either the 47-position live pack (no duplicate remake) or the
    # 48-position variant. This prevents one optional duplicate from shifting
    # all sticker meanings that follow it.
    async def ensure_aug19_catalog(bot, *, force: bool = False):
        if sticker_runtime._STICKER_IDS and sticker_runtime._STICKER_UNIQUE_IDS and not force:
            return sticker_runtime._STICKER_IDS

        sticker_set = await bot.get_sticker_set(sticker_engine.STICKER_SET_NAME)
        stickers = tuple(sticker_set.stickers or ())
        active_order = _active_order_for_count(len(stickers))

        outgoing: dict[str, str] = {}
        incoming: dict[str, str] = {}
        for index, key in enumerate(active_order):
            sticker = stickers[index]
            outgoing[key] = sticker.file_id
            incoming[sticker.file_unique_id] = key

        sticker_runtime._STICKER_IDS = outgoing
        sticker_runtime._STICKER_UNIQUE_IDS = incoming
        sticker_runtime._save_sticker_ids(outgoing)
        logging.warning(
            "Yayceslav Aug19 sticker catalog resolved: live=%s mapped=%s duplicate_remake=%s",
            len(stickers),
            len(active_order),
            "pereigral_i_unichtozhil_new" in active_order,
        )
        return outgoing

    ensure_aug19_catalog._yayceslav_aug19 = True
    sticker_runtime.ensure_sticker_catalog = ensure_aug19_catalog

    # If the live pack has the 47-position layout, requests for the new visual
    # PEREIGRAL fall back to the already-existing PEREIGRAL sticker.
    original_reply_by_key = sticker_runtime.reply_sticker_by_key
    if not getattr(original_reply_by_key, "_yayceslav_aug19", False):
        @functools.wraps(original_reply_by_key)
        async def reply_by_key_aug19(update, context, sticker_key: str):
            key = sticker_key
            if key == "pereigral_i_unichtozhil_new":
                mapping = await sticker_runtime.ensure_sticker_ids(context.bot)
                if key not in mapping:
                    key = "pereigral_i_unichtozhil"
            return await original_reply_by_key(update, context, key)

        reply_by_key_aug19._yayceslav_aug19 = True
        sticker_runtime.reply_sticker_by_key = reply_by_key_aug19

    original_choose_post_tag = sticker_post_runtime.choose_post_text_tag
    if not getattr(original_choose_post_tag, "_yayceslav_aug19", False):
        @functools.wraps(original_choose_post_tag)
        def choose_post_tag_aug19(source_user_text: str, answer_text: str):
            source = str(source_user_text or "")
            answer = str(answer_text or "")
            tag = original_choose_post_tag(source, answer)
            if tag == "pereigral_i_unichtozhil":
                return "pereigral_i_unichtozhil_new"
            if sticker_engine.is_serious_text(source) or sticker_engine.is_serious_text(answer):
                return tag
            if _DOOM_ANSWER_RE.search(answer):
                return "vse_tlen"
            if len(answer) >= 20 and _PROBLEM_RE.search(source):
                return "kto_opyat_ne_spravilsya"
            return tag

        choose_post_tag_aug19._yayceslav_aug19 = True
        sticker_post_runtime.choose_post_text_tag = choose_post_tag_aug19

    # Repeated insults: only once the existing hostile streak reaches 3+ turns.
    original_maybe_post_tag = sticker_post_runtime.maybe_send_post_text_tag
    if not getattr(original_maybe_post_tag, "_yayceslav_aug19", False):
        @functools.wraps(original_maybe_post_tag)
        async def maybe_post_tag_aug19(update, context, source_user_text: str, answer_text: str):
            chat = getattr(update, "effective_chat", None)
            user = getattr(update, "effective_user", None)
            if chat and user and personality.HOSTILE_RE.search(str(source_user_text or "")):
                streak = hostile_streak_engine.current(chat.id, user.id)
                if streak >= 3 and random.random() < 0.35:
                    now = time.monotonic()
                    if sticker_runtime.sticker_slot_allowed(chat.id, user.id, now):
                        try:
                            sent = await sticker_runtime.reply_sticker_by_key(
                                update, context, "nu_i_suka_zhe_ty"
                            )
                        except Exception as error:
                            logging.warning("Repeated-insult sticker failed: %s", error)
                            sent = False
                        if sent:
                            sticker_runtime._record_sticker_slot(chat.id, user.id, now)
                            return True
            return await original_maybe_post_tag(
                update, context, source_user_text, answer_text
            )

        maybe_post_tag_aug19._yayceslav_aug19 = True
        sticker_post_runtime.maybe_send_post_text_tag = maybe_post_tag_aug19

    # Rate-limit exhaustion: preserve the existing text warning and append
    # ВСЁ ТЛЕН at most once through the shared sticker cooldown gate.
    bot_module = _find_bot_module()
    if bot_module is not None:
        original_rate_limit = bot_module.enforce_rate_limit
        if not getattr(original_rate_limit, "_yayceslav_tlen_rate_limit", False):
            @functools.wraps(original_rate_limit)
            async def rate_limit_with_tlen(update, bucket: str):
                allowed = await original_rate_limit(update, bucket)
                if allowed:
                    return True

                chat = getattr(update, "effective_chat", None)
                user = getattr(update, "effective_user", None)
                if not chat or not user:
                    return False
                now = time.monotonic()
                if not sticker_runtime.sticker_slot_allowed(chat.id, user.id, now):
                    return False
                try:
                    sent = await sticker_runtime.reply_sticker_by_key(
                        update, getattr(update, "_context", None), "vse_tlen"
                    )
                except Exception:
                    # Normal PTB Update has no context reference, so the generic
                    # wrapper cannot safely send here. The rate-limit semantic is
                    # still available through doom/fatigue and post-answer paths.
                    sent = False
                if sent:
                    sticker_runtime._record_sticker_slot(chat.id, user.id, now)
                return False

            rate_limit_with_tlen._yayceslav_tlen_rate_limit = True
            bot_module.enforce_rate_limit = rate_limit_with_tlen

    _INSTALLED_RUNTIME = True
