import sqlite3

import relationship_memory_v2_runtime as rel


def test_marker_classifier_requires_direct_bot_interaction():
    assert rel.classify_social_markers("ахаха, спасибо", replying_to_bot=False) == ()
    markers = rel.classify_social_markers("ахаха, спасибо, но ты ошибся", replying_to_bot=True)
    assert "banter" in markers
    assert "gratitude" in markers
    assert "correction" in markers


def test_snapshot_uses_observed_history_not_personality_inference():
    snapshot = rel.build_relationship_snapshot(
        {
            "total_messages": 120,
            "replies_to_bot": 22,
            "insults_to_bot": 2,
            "relationship_level": 3,
            "callback_terms": ["Steam", "Abaqus"],
        },
        {"banter": 7, "correction": 2, "reconciliation": 1},
    )
    assert "Steam" in snapshot
    assert "Abaqus" in snapshot
    assert "mutual banter/laughter x7" in snapshot
    assert "user corrected Yayceslav x2" in snapshot
    assert "personality" not in snapshot.lower()


def test_instruction_prioritizes_current_turn_and_blocks_sensitive_inference():
    instruction = rel.build_relationship_instruction("relationship events: explicit disagreement x4")
    assert "Current message and current tone override old history" in instruction
    assert "Old conflict never authorizes attacking a neutral turn" in instruction
    assert "health, finances, politics, religion, sexuality" in instruction
    assert "Never leak relationship memory across chats or users" in instruction


def test_marker_storage_is_scoped_by_chat_and_user(tmp_path):
    db_path = tmp_path / "relationship.sqlite"

    class Bot:
        @staticmethod
        def get_db_connection():
            return sqlite3.connect(db_path)

    rel._initialize_table(Bot)
    rel._record_markers_sync(Bot, -100, 1, ("banter", "correction"))
    rel._record_markers_sync(Bot, -100, 1, ("banter",))
    rel._record_markers_sync(Bot, -100, 2, ("gratitude",))
    rel._record_markers_sync(Bot, -200, 1, ("apology",))

    assert rel._load_markers_sync(Bot, -100, 1) == {"banter": 2, "correction": 1}
    assert rel._load_markers_sync(Bot, -100, 2) == {"gratitude": 1}
    assert rel._load_markers_sync(Bot, -200, 1) == {"apology": 1}


def test_prompt_wrapper_injects_only_current_group_member_history(tmp_path, monkeypatch):
    db_path = tmp_path / "wrapper.sqlite"

    class Bot:
        _yayceslav_relationship_memory_v2_installed = False

        @staticmethod
        def get_db_connection():
            return sqlite3.connect(db_path)

        @staticmethod
        def get_member_profile_sync(chat_id, user_id):
            if (chat_id, user_id) == (-100, 7):
                return {
                    "total_messages": 55,
                    "replies_to_bot": 9,
                    "insults_to_bot": 0,
                    "relationship_level": 2,
                    "callback_terms": ["Steam"],
                }
            return {}

        @staticmethod
        def build_full_system_instruction(*, chat_id, chat_type, user_id):
            return "BASE"

    monkeypatch.setattr(rel, "_INSTALLED", False)
    rel._initialize_table(Bot)
    rel._record_markers_sync(Bot, -100, 7, ("banter", "gratitude"))
    assert rel.install(Bot) is True

    group_prompt = Bot.build_full_system_instruction(chat_id=-100, chat_type="supergroup", user_id=7)
    assert group_prompt.startswith("BASE")
    assert "RELATIONSHIP MEMORY V2" in group_prompt
    assert "Steam" in group_prompt
    assert "mutual banter/laughter x1" in group_prompt

    other_user = Bot.build_full_system_instruction(chat_id=-100, chat_type="supergroup", user_id=8)
    assert other_user == "BASE"

    private_prompt = Bot.build_full_system_instruction(chat_id=7, chat_type="private", user_id=7)
    assert private_prompt == "BASE"
