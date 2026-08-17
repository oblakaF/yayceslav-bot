import sticker_engine


def test_sticker_map_references_only_known_stickers():
    known = set(sticker_engine.STICKER_ORDER)
    assert len(sticker_engine.STICKER_ORDER) == 29
    assert set(sticker_engine.STICKER_LABELS) == known
    assert all(
        key in known
        for pool in sticker_engine.EVENT_STICKERS.values()
        for key in pool
    )


def test_obvious_events_are_detected():
    cases = {
        "где пруфы на эту хуйню": "proof",
        "пятница пора бухать": "friday",
        "слава пращуру": "ancestor",
        "кринж полный": "cringe",
        "ну это skill issue": "skill_issue",
        "минус аура": "aura_loss",
        "он его переиграл и уничтожил": "outplayed",
        "завали ебало": "shut_up",
        "иди нахуй": "dismissal",
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


def test_unknown_event_has_zero_background_chance():
    assert sticker_engine.event_chance("definitely_unknown") == 0.0
