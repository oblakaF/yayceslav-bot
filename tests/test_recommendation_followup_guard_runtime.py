import book_recommendation_runtime as books
import game_recommendation_runtime as games
import movie_recommendation_runtime as movies
import recommendation_followup_guard_runtime as guard


def setup_function():
    guard._ACTIVE_CATEGORY_BY_CHAT.clear()
    books._BOOK_TOPIC_BY_CHAT.clear()
    movies._MOVIE_TOPIC_BY_CHAT.clear()
    games._GAME_TOPIC_BY_CHAT.clear()


def test_latest_explicit_category_owns_generic_followup():
    chat_id = -100

    assert games.classify_game_recommendation_intent(
        "посоветуй игры по типу киберпанк", chat_id=chat_id
    ) == "Cyberpunk 2077"
    games.remember_game_topic(chat_id, "Cyberpunk 2077", 1091500, now=100.0)
    assert guard.active_category(chat_id) == "games"

    assert movies.classify_movie_recommendation_intent(
        "посоветуй фильмы в духе Дюны", chat_id=chat_id
    ) == "Дюны"
    movies.remember_movie_topic(chat_id, "Дюна", 438631, now=100.0)
    assert guard.active_category(chat_id) == "movies"

    # Both specialist seed memories still exist, but handler order must no longer
    # decide the meaning of a category-less follow-up.
    assert games.current_game_topic(chat_id, now=101.0).name == "Cyberpunk 2077"
    assert movies.current_movie_topic(chat_id, now=101.0).title == "Дюна"
    assert games.classify_game_recommendation_intent("а ещё?", chat_id=chat_id) == ""
    assert movies.classify_movie_recommendation_intent("а ещё?", chat_id=chat_id) == "Дюна"
    assert books.classify_book_recommendation_intent("а ещё?", chat_id=chat_id) == ""


def test_explicit_category_named_followup_can_switch_owner_back():
    chat_id = -101
    games.remember_game_topic(chat_id, "Cyberpunk 2077", 1091500)
    movies.remember_movie_topic(chat_id, "Дюна", 438631)
    guard.remember_active_category(chat_id, "movies")

    assert games.classify_game_recommendation_intent("ещё игры", chat_id=chat_id) == "Cyberpunk 2077"
    assert guard.active_category(chat_id) == "games"
    assert movies.classify_movie_recommendation_intent("а ещё?", chat_id=chat_id) == ""
    assert games.classify_game_recommendation_intent("а ещё?", chat_id=chat_id) == "Cyberpunk 2077"


def test_owner_is_chat_local_and_expires():
    guard.remember_active_category(-200, "books", now=100.0)
    guard.remember_active_category(-300, "games", now=100.0)

    assert guard.active_category(-200, now=101.0) == "books"
    assert guard.active_category(-300, now=101.0) == "games"
    assert guard.active_category(-400, now=101.0) == ""
    assert guard.active_category(-200, now=100.0 + guard.OWNER_TTL_SECONDS + 1) == ""


def test_only_categoryless_phrases_are_guarded():
    assert guard.is_generic_followup("а ещё?") is True
    assert guard.is_generic_followup("что ещё") is True
    assert guard.is_generic_followup("а похожее") is True
    assert guard.is_generic_followup("ещё игры") is False
    assert guard.is_generic_followup("ещё фильмы") is False
    assert guard.is_generic_followup("ещё книги") is False
