import bot


def test_hard_trigger_word_boundary_excludes_substring():
    # "гой" is a substring of "другой" but must not match as a whole word.
    assert bot.hard_trigger_found("другой вариант", "гой") is False


def test_hard_trigger_word_boundary_matches_whole_word():
    assert bot.hard_trigger_found("это просто гой", "гой") is True
    assert bot.hard_trigger_found("не гойда, а обычный текст", "гойда") is True


def test_six_seven_trigger_is_numeric_word_boundary():
    assert bot.hard_trigger_found("этот угол примерно 67 градусов", "67") is True
    assert bot.hard_trigger_found("год основания 1967", "67") is False


def test_choose_hard_trigger_reply_matches_goy_variants():
    assert bot.choose_hard_trigger_reply("гойда, все свои") in bot.GOY_REPLIES
    assert bot.choose_hard_trigger_reply("это просто гой") in bot.GOY_REPLIES


def test_choose_hard_trigger_reply_none_for_unrelated_text_with_substring():
    assert bot.choose_hard_trigger_reply("другой вариант, давай его") is None


def test_choose_hard_trigger_reply_none_for_plain_text():
    assert bot.choose_hard_trigger_reply("привет, как дела?") is None


def test_choose_hard_trigger_reply_yayceslav_mention():
    assert bot.choose_hard_trigger_reply(
        "Яйцеслав, ты вообще как?"
    ) in bot.YAYCESLAV_REPLIES


def test_base_word_still_triggers_hard_reply_known_gap():
    """Known gap (see roadmap Phase 2/6): word-boundary regex cannot tell
    slang "база" apart from "база данных" — this documents current
    behaviour so a future intent-aware fix has a test to update, not a
    silent regression."""

    assert bot.choose_hard_trigger_reply(
        "какая сегодня база данных лучше?"
    ) in bot.BASE_REPLIES
