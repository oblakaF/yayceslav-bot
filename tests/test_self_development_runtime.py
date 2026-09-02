import sqlite3

import self_canon_runtime
import self_development_runtime as dev


class FakeBot:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute(
            """
            CREATE TABLE chat_self_canon (
                chat_id INTEGER NOT NULL,
                trait_key TEXT NOT NULL,
                trait_value TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY(chat_id, trait_key)
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE chat_semantic_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                author TEXT NOT NULL DEFAULT '',
                modality TEXT NOT NULL DEFAULT 'text',
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        self.connection.commit()

    def get_db_connection(self):
        return self.connection


def _mature_bot():
    bot = FakeBot()
    dev._initialize_table(bot)
    bot.connection.execute(
        "INSERT INTO chat_self_canon(chat_id, trait_key, trait_value) VALUES (1, 'music', 'darkwave')"
    )
    statements = [
        ("Мне нравится dark ambient, когда хочется тишины.", "-10 days"),
        ("Я предпочитаю dark ambient поздно вечером.", "-8 days"),
        ("Я слушаю dark ambient всё чаще.", "-6 days"),
        ("Мне ближе dark ambient, чем шумный плейлист.", "-4 days"),
        ("Я люблю dark ambient за пространство.", "-2 days"),
        ("Я выбираю dark ambient, когда работаю.", "-1 days"),
    ]
    for text, offset in statements:
        bot.connection.execute(
            """
            INSERT INTO chat_semantic_history(chat_id, role, content, created_at)
            VALUES (1, 'assistant', ?, datetime('now', ?))
            """,
            (text, offset),
        )
    bot.connection.commit()
    return bot


def test_marker_allows_only_one_low_or_selected_medium_trait():
    clean, updates = dev.strip_and_parse_marker(
        'Я подумал, что теперь мне ближе старый darkwave плюс dark ambient, потому что я к нему постоянно возвращаюсь.\n'
        '[[YAY_SELF_DEVELOPMENT {"set":{"origin":"Марс","music":"darkwave + dark ambient","aesthetic":"минимализм"}}]]'
    )
    assert "YAY_SELF_DEVELOPMENT" not in clean
    assert updates == {"music": "darkwave + dark ambient"}
    assert "origin" not in dev._ALLOWED_TRAITS
    assert "values" not in dev._ALLOWED_TRAITS


def test_malformed_marker_is_hidden_and_not_persistable():
    clean, updates = dev.strip_and_parse_marker(
        "Обычный ответ.\n[[YAY_SELF_DEVELOPMENT nope]]"
    )
    assert clean == "Обычный ответ."
    assert updates == {}


def test_development_window_requires_reflective_turn_and_mature_history():
    bot = _mature_bot()
    block = dev.development_context(bot, 1, "Что ты сейчас слушаешь и изменился ли твой вкус?")
    assert "RARE SELF-DEVELOPMENT WINDOW" in block
    assert "darkwave" in block
    assert "dark ambient" in block
    assert "максимум ОДНУ" in block
    assert dev.development_context(bot, 1, "Сколько будет два плюс два?") == ""


def test_development_window_requires_multiple_days_and_span():
    bot = FakeBot()
    dev._initialize_table(bot)
    bot.connection.execute(
        "INSERT INTO chat_self_canon(chat_id, trait_key, trait_value) VALUES (1, 'hobbies', 'шахматы')"
    )
    for index in range(6):
        bot.connection.execute(
            "INSERT INTO chat_semantic_history(chat_id, role, content) VALUES (1, 'assistant', ?)",
            (f"Мне нравится го, наблюдение {index}.",),
        )
    bot.connection.commit()
    assert dev.development_context(bot, 1, "Что тебе сейчас нравится?") == ""


def test_cooldown_blocks_second_development_window():
    bot = _mature_bot()
    bot.connection.execute(
        """
        INSERT INTO chat_self_development_events(chat_id, trait_key, old_value, new_value)
        VALUES (1, 'music', 'darkwave', 'darkwave + dark ambient')
        """
    )
    bot.connection.commit()
    assert dev.development_context(bot, 1, "Что ты сейчас слушаешь?") == ""


def test_allowed_traits_never_include_high_inertia_identity():
    forbidden = {"origin", "profession", "values", "gender", "ethnicity", "political_taste"}
    assert dev._ALLOWED_TRAITS.isdisjoint(forbidden)
    assert "music" in dev._ALLOWED_TRAITS
    assert "hobbies" in dev._ALLOWED_TRAITS
    assert "aesthetic" in dev._ALLOWED_TRAITS
