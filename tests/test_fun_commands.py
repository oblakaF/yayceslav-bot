import bot


def test_anti_advice_forbidden_topics_detected():
    assert bot._ANTI_ADVICE_FORBIDDEN_RE.search("как лечить простуду")
    assert bot._ANTI_ADVICE_FORBIDDEN_RE.search("нужен юрист для суда")
    assert bot._ANTI_ADVICE_FORBIDDEN_RE.search("куда вложить инвестиции")


def test_anti_advice_allows_safe_topics():
    assert bot._ANTI_ADVICE_FORBIDDEN_RE.search("как готовиться к экзамену") is None
    assert bot._ANTI_ADVICE_FORBIDDEN_RE.search("как быстро выучить питон") is None


def test_pending_duels_starts_empty_dict_type():
    assert isinstance(bot.PENDING_DUELS, dict)


def test_story_state_is_a_defaultdict_of_lists():
    chat_id = 777001
    bot.STORY_STATE.pop(chat_id, None)
    assert bot.STORY_STATE[chat_id] == []
