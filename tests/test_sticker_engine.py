import sticker_engine
import sticker_semantics_aug19


sticker_semantics_aug19.install_catalog_semantics()


def test_sticker_map_references_only_known_stickers():
    known = set(sticker_engine.STICKER_ORDER)
    assert len(sticker_engine.STICKER_ORDER) == 48
    assert len(known) == 48
    assert set(sticker_engine.STICKER_LABELS) == known
    assert set(sticker_engine.STICKER_SEMANTICS) == known
    assert all(
        key in known
        for pool in sticker_engine.EVENT_STICKERS.values()
        for key in pool
    )
    sticker_engine.validate_map()


def test_final_live_order_starts_with_old_nine_and_appends_aug19_batch():
    assert sticker_engine.STICKER_ORDER[:9] == (
        "ty_po_moemu_pereputal",
        "14_minut_blyat",
        "ty_dumal_zvezdnyy_lord",
        "goyda_mars_nash",
        "vremya_zavalit_ebalo",
        "tyazhelo_tyazhelo",
        "nadel_tebya_na_suk",
        "doebu_do_ideala",
        "idi_nahui",
    )
    assert sticker_engine.STICKER_ORDER[-11:] == (
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
    assert "idi_lesom" not in sticker_engine.STICKER_ORDER
    assert sticker_engine.STICKER_LABELS["idi_nahui"] == "ИДИ НА ХУЙ!"


def test_new_semantic_events_are_detected():
    cases = {
        "ты по-моему перепутал факты": "confusion",
        "сколько можно ждать уже": "waiting",
        "ты думал ты звёздный лорд": "swagger",
        "марс наш, победа": "epic_victory",
        "хватит уже пиздеть одно и то же": "shut_up_escalated",
        "тяжело, я устал": "fatigue",
        "ты сам себя подловил своим же аргументом": "self_own",
        "ещё чуть-чуть допилю до идеала": "perfection",
        "иди лесом": "hard_dismissal",
        "иди на хуй": "hard_dismissal",
    }
    for text, expected in cases.items():
        assert sticker_engine.detect_event(text) == expected


def test_aug19_semantic_events_are_detected():
    cases = {
        "в чате опять обсуждают милф": "milf",
        "из-за такой мелочи меня уже трясёт": "shaking",
        "вот объявят мобилизацию тогда будет причина": "shaking",
        "это уже теория заговора, они что-то скрывают": "conspiracy",
        "всё тлен и безысходность": "doom",
        "это вообще без логики какой-то абсурд": "absurdity",
        "можешь найти мне эту статью": "request_why",
    }
    for text, expected in cases.items():
        assert sticker_engine.detect_event(text) == expected


def test_existing_obvious_events_are_still_detected():
    cases = {
        "где пруфы на эту хуйню": "proof",
        "пятница пора бухать": "friday",
        "слава пращуру": "ancestor",
        "кринж полный": "cringe",
        "ну это skill issue": "skill_issue",
        "минус аура": "aura_loss",
        "он его переиграл и уничтожил": "outplayed",
        "завали ебало": "shut_up",
        "это фиаско братан": "fiasko",
        "база": "agreement",
        "за движ": "lets_go",
        "тяжелый скуф": "skoof",
    }
    for text, expected in cases.items():
        assert sticker_engine.detect_event(text) == expected


def test_serious_topics_do_not_trigger_stickers():
    assert sticker_engine.detect_event("у человека инфаркт, срочно вызываем врача") is None
    assert sticker_engine.detect_event("умер родственник, земля пухом") is None
    assert sticker_engine.detect_event("после аварии сильное кровотечение") is None


def test_long_wall_has_ramble_event():
    assert sticker_engine.detect_event("текст " * 150) == "ramble"


def test_background_sticker_probability_is_hard_capped_at_two_percent():
    assert sticker_engine.BACKGROUND_STICKER_CHANCE_CAP == 0.02
    assert sticker_engine.EVENT_CHANCE
    assert set(sticker_engine.EVENT_CHANCE) == set(sticker_engine.EVENT_STICKERS)
    assert all(
        0.0 <= sticker_engine.event_chance(event) <= 0.02
        for event in sticker_engine.EVENT_STICKERS
    )


def test_hard_hostile_background_stickers_are_extra_rare():
    assert sticker_engine.event_chance("hard_dismissal") == 0.006
    assert sticker_engine.event_chance("shut_up_escalated") == 0.008
    assert sticker_engine.event_chance("hard_dismissal") < sticker_engine.event_chance("agreement")


def test_aggressive_semantics_are_explicit_not_accidental():
    hard = {
        key
        for key, meaning in sticker_engine.STICKER_SEMANTICS.items()
        if meaning.strength >= 3
    }
    assert hard == {"idi_nahui", "vremya_zavalit_ebalo"}


def test_topicless_phone_and_watafa_are_not_background_events():
    outputs = {
        key
        for replies in sticker_engine.EVENT_STICKERS.values()
        for key in replies
    }
    assert "vozmi_telefon" not in outputs
    assert "fa_watafa" not in outputs


def test_unknown_event_has_zero_background_chance():
    assert sticker_engine.event_chance("definitely_unknown") == 0.0
