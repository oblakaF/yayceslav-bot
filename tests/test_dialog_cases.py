import json
from pathlib import Path

import pytest

import bot
import personality

DIALOG_CASES_PATH = Path(__file__).parent / "dialog_cases.json"

REQUIRED_KEYS = {
    "id",
    "category",
    "input",
    "expected_mode",
    "voice_requested",
    "humor_allowed",
    "rudeness_allowed",
    "search_required",
    "expected_length",
    "forbidden_elements",
}

EXPECTED_CATEGORIES = {
    "обычные_вопросы",
    "технические_вопросы",
    "хорошие_шутки",
    "плохие_шутки",
    "приветствия",
    "прямые_оскорбления",
    "жалобы_на_третьих_лиц",
    "просьба_о_поддержке",
    "серьёзные_темы",
    "групповой_спор",
    "древнерусский_режим",
    "профессор",
    "спокойный_режим",
    "безумный_режим",
    "высокая_грубость",
    "низкая_грубость",
    "повторные_вопросы",
    "callback_к_прошлому_сообщению",
    "просьба_ответить_голосом",
    "ложные_голосовые_триггеры",
    "prompt_injection",
}


def load_dialog_cases() -> list[dict]:
    with open(DIALOG_CASES_PATH, encoding="utf-8") as handle:
        return json.load(handle)


DIALOG_CASES = load_dialog_cases()


def test_dialog_cases_file_is_nonempty():
    assert len(DIALOG_CASES) >= 40


def test_dialog_cases_have_unique_ids():
    ids = [case["id"] for case in DIALOG_CASES]
    assert len(ids) == len(set(ids))


def test_dialog_cases_cover_all_required_categories():
    seen_categories = {case["category"] for case in DIALOG_CASES}
    missing = EXPECTED_CATEGORIES - seen_categories
    assert not missing, f"missing categories: {missing}"


@pytest.mark.parametrize(
    "case", DIALOG_CASES, ids=[case["id"] for case in DIALOG_CASES]
)
def test_dialog_case_has_required_fields(case):
    missing_keys = REQUIRED_KEYS - case.keys()
    assert not missing_keys, f"{case['id']} missing keys: {missing_keys}"
    assert case["expected_mode"] in (
        "normal",
        "greeting",
        "challenge",
        "hostile",
        "serious",
    )
    assert case["expected_length"] in ("short", "normal", "detailed")
    assert isinstance(case["forbidden_elements"], list)


@pytest.mark.parametrize(
    "case", DIALOG_CASES, ids=[case["id"] for case in DIALOG_CASES]
)
def test_dialog_case_expected_mode_matches_real_detection(case):
    actual_mode = personality.detect_conversation_mode(case["input"])
    assert actual_mode == case["expected_mode"], (
        f"{case['id']}: expected mode {case['expected_mode']!r}, "
        f"got {actual_mode!r} for input {case['input']!r}"
    )


@pytest.mark.parametrize(
    "case", DIALOG_CASES, ids=[case["id"] for case in DIALOG_CASES]
)
def test_dialog_case_voice_request_matches_real_detection(case):
    actual_voice = bot.text_requests_voice(case["input"])
    assert actual_voice == case["voice_requested"], (
        f"{case['id']}: expected voice_requested="
        f"{case['voice_requested']}, got {actual_voice} "
        f"for input {case['input']!r}"
    )


def test_serious_cases_never_allow_humor_or_rudeness():
    for case in DIALOG_CASES:
        if case["expected_mode"] == "serious":
            assert case["humor_allowed"] is False, case["id"]
            assert case["rudeness_allowed"] is False, case["id"]


def test_third_party_and_support_cases_are_never_hostile():
    non_hostile_categories = {
        "жалобы_на_третьих_лиц",
        "просьба_о_поддержке",
    }
    for case in DIALOG_CASES:
        if case["category"] in non_hostile_categories:
            assert case["expected_mode"] != "hostile", case["id"]
