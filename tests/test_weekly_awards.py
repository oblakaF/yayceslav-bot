import bot


def _activity(user_id, **kwargs):
    entry = {
        "user_id": user_id,
        "messages": 0,
        "text_characters": 0,
        "voice_messages": 0,
        "voice_duration_seconds": 0,
        "photos": 0,
        "videos": 0,
        "stickers": 0,
        "documents": 0,
        "replies": 0,
        "replies_to_bot": 0,
        "commands": 0,
        "night_messages": 0,
        "questions": 0,
        "links": 0,
        "edited_messages": 0,
    }
    entry.update(kwargs)
    return entry


def test_chat_leader_picks_the_highest_message_count():
    weekly = [
        _activity(1, messages=10),
        _activity(2, messages=25),
        _activity(3, messages=5),
    ]
    awards = dict(bot.compute_weekly_awards(weekly, known_members=[]))
    assert awards["chat_leader"] == 2


def test_no_award_when_everyone_is_at_zero():
    weekly = [_activity(1), _activity(2)]
    awards = dict(bot.compute_weekly_awards(weekly, known_members=[]))
    assert "chat_leader" not in awards
    assert "voice_leader" not in awards


def test_one_word_sage_requires_minimum_messages():
    weekly = [
        # Both below the 5-message minimum -- nobody should qualify.
        _activity(1, messages=2, text_characters=2),
        _activity(2, messages=3, text_characters=6),
    ]
    awards = dict(bot.compute_weekly_awards(weekly, known_members=[]))
    assert "one_word_sage" not in awards


def test_one_word_sage_picks_shortest_average_length():
    weekly = [
        _activity(1, messages=10, text_characters=20),  # avg 2
        _activity(2, messages=10, text_characters=500),  # avg 50
    ]
    awards = dict(bot.compute_weekly_awards(weekly, known_members=[]))
    assert awards["one_word_sage"] == 1


def test_silent_observer_only_for_previously_active_member():
    weekly = [_activity(1, messages=5)]
    known_members = [
        {"user_id": 1, "total_messages": 50},
        {"user_id": 2, "total_messages": 30},  # known, active before, silent now
        {"user_id": 3, "total_messages": 0},  # never posted -- not eligible
    ]
    awards = dict(bot.compute_weekly_awards(weekly, known_members))
    assert awards["silent_observer"] == 2


def test_no_silent_observer_when_everyone_known_is_active():
    weekly = [_activity(1, messages=5)]
    known_members = [{"user_id": 1, "total_messages": 50}]
    awards = dict(bot.compute_weekly_awards(weekly, known_members))
    assert "silent_observer" not in awards


def test_format_awards_message_handles_empty_list():
    message = bot.format_awards_message([], {})
    assert "маловато" in message


def test_format_awards_message_includes_display_name():
    message = bot.format_awards_message(
        [("chat_leader", 1)], {1: "Тестовый Герой"}
    )
    assert "Тестовый Герой" in message
    assert "Срун чата" in message
