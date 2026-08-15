import ast
from pathlib import Path

import bot
import intent
import passive_engine
import reaction_engine
import state_engine
import title_pools


def _update_based_missing_ask_context():
    source = Path("bot.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    missing = []

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.stack = []
        def visit_AsyncFunctionDef(self, node):
            self.stack.append(node)
            self.generic_visit(node)
            self.stack.pop()
        def visit_FunctionDef(self, node):
            self.stack.append(node)
            self.generic_visit(node)
            self.stack.pop()
        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == "ask_gemini" and self.stack:
                fn = self.stack[-1]
                fn_args = {a.arg for a in list(fn.args.args) + list(fn.args.kwonlyargs)}
                if "update" in fn_args:
                    kws = {kw.arg for kw in node.keywords if kw.arg}
                    absent = {"chat_id", "chat_type", "user_id"} - kws
                    if absent:
                        missing.append((fn.name, node.lineno, absent))
            self.generic_visit(node)
    Visitor().visit(tree)
    return missing


def test_every_update_based_ask_gemini_call_has_identity_context():
    assert _update_based_missing_ask_context() == []


def test_missing_chat_does_not_touch_shared_state_key_zero(monkeypatch):
    state_engine.reset_state()
    bot.build_full_system_instruction("обычный вопрос", chat_id=None, user_id=None)
    assert 0 not in state_engine._CHAT_STATE


def test_daily_title_rolls_back_if_member_profile_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "STATS_DB_PATH", tmp_path / "audit-title.db")
    bot.initialize_stats_database()
    with bot.get_db_connection() as connection:
        connection.execute("INSERT INTO chats (chat_id, chat_type) VALUES (?, 'group')", (-9001,))
        connection.execute("INSERT INTO users (user_id) VALUES (?)", (991,))
        connection.commit()
    assert not bot.try_assign_daily_title_sync(-9001, "2026-08-15", 991, "Товарищ майор")
    assert bot.get_daily_title_assignment_sync(-9001, "2026-08-15") is None


def test_v2_title_picker_is_real_two_stage_picker(monkeypatch):
    monkeypatch.setattr(title_pools, "pick_title", lambda previous_title=None: "Товарищ майор")
    assert bot.pick_new_title("Скуф") == "Товарищ майор"


def test_mysticism_regex_matches_natural_inflection():
    assert reaction_engine.detect_context_reason("звезды говорят, что мне повезет") == "mysticism"


def test_dead_argument_regex_matches_natural_inflection():
    assert reaction_engine.detect_context_reason("аргумент развалился на глазах") == "dead_argument"


def test_drama_regex_matches_inflections():
    assert reaction_engine.detect_context_reason("он опять стучал и слил переписку") == "suspicious_drama"
    assert reaction_engine.detect_context_reason("какая-то крыса слила инфу") == "suspicious_drama"


def test_full_nonsense_disagreement_variants():
    assert intent.classify_intent("это полный бред")[0] == "disagreement"
    assert intent.classify_intent("бред полный вообще")[0] == "disagreement"


def test_latest_temporary_state_wins():
    state_engine.reset_state()
    state_engine.mark_annoyed(1, now=1000.0)
    state_engine.mark_argumentative(1, now=1001.0)
    assert state_engine.resolve_state(1, conversation_mode="normal", now=1002.0, record=False) == "argumentative"
    state_engine.reset_state()
    state_engine.mark_argumentative(2, now=1000.0)
    state_engine.mark_annoyed(2, now=1001.0)
    assert state_engine.resolve_state(2, conversation_mode="normal", now=1002.0, record=False) == "annoyed"


def test_short_acknowledgements_never_allow_random_text():
    for text in ("100%", "да", "нет", "точно", "согласен", "ок", "+1", "👍"):
        assert not passive_engine.random_text_intervention_allowed(text, "provocation")


def test_good_question_does_not_justify_random_hard_reply():
    assert not passive_engine.random_text_intervention_allowed(
        "Яблоко сняли с выборов, удивлен? нет", "good_question"
    )


def test_contextual_provocation_can_still_open_passive_slot():
    assert passive_engine.random_text_intervention_allowed(
        "ну давай, докажи если сможешь", "provocation"
    )


def test_legacy_random_reply_fallback_removed_from_hard_listener():
    source = Path("bot.py").read_text(encoding="utf-8")
    start = source.index("async def hard_mode_listener(")
    end = source.index("async def enforce_rate_limit(", start)
    hard_listener = source[start:end]
    assert "random.choice(HARD_RANDOM_REPLIES)" not in hard_listener
