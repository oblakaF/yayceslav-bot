import pytest

import recent_video_note_runtime as runtime


@pytest.fixture(autouse=True)
def clear_recent_video_notes():
    runtime._RECENT_VIDEO_NOTES.clear()
    yield
    runtime._RECENT_VIDEO_NOTES.clear()


@pytest.mark.parametrize(
    "text",
    [
        "Яйцеслав, че по кружку?",
        "что скажешь по прошлому видео?",
        "посмотри предыдущий кружок",
        "глянь видео выше",
        "как тебе последний видос?",
        "что там в кружке?",
        "я там кружок скинул прошлым сообщением, че по нему скажешь",
        "кружок прошлым сообщением",
    ],
)
def test_followup_phrases_are_high_confidence(text):
    assert runtime.is_recent_video_note_followup(text)


@pytest.mark.parametrize(
    "text",
    [
        "как дела",
        "я люблю видео",
        "скинул кружок",
        "кружок сегодня красивый",
        "что думаешь про кино",
        "посмотри новости",
    ],
)
def test_normal_chat_does_not_trigger_video_followup(text):
    assert not runtime.is_recent_video_note_followup(text)


def test_recent_video_note_is_returned_inside_ttl():
    runtime.remember_recent_video_note(
        -100,
        file_id="video-file-id",
        message_id=42,
        sender_id=7,
        file_size=1234,
        now=1000.0,
    )

    item = runtime.get_recent_video_note(-100, now=1100.0)

    assert item is not None
    assert item.file_id == "video-file-id"
    assert item.message_id == 42
    assert item.sender_id == 7
    assert item.file_size == 1234


def test_recent_video_note_expires_after_ttl():
    runtime.remember_recent_video_note(
        -100,
        file_id="video-file-id",
        message_id=42,
        sender_id=7,
        now=1000.0,
    )

    assert runtime.get_recent_video_note(
        -100,
        now=1000.0 + runtime.RECENT_VIDEO_NOTE_TTL_SECONDS + 0.01,
    ) is None


def test_newer_circle_replaces_older_circle_in_same_chat():
    runtime.remember_recent_video_note(
        -100,
        file_id="old",
        message_id=1,
        sender_id=7,
        now=1000.0,
    )
    runtime.remember_recent_video_note(
        -100,
        file_id="new",
        message_id=2,
        sender_id=8,
        now=1001.0,
    )

    item = runtime.get_recent_video_note(-100, now=1002.0)

    assert item is not None
    assert item.file_id == "new"
    assert item.message_id == 2
    assert item.sender_id == 8


def test_cache_is_hard_capped(monkeypatch):
    monkeypatch.setattr(runtime, "MAX_RECENT_VIDEO_NOTE_CHATS", 2)

    for index in range(3):
        runtime.remember_recent_video_note(
            -(index + 1),
            file_id=f"file-{index}",
            message_id=index,
            sender_id=index,
            now=1000.0 + index,
        )

    assert len(runtime._RECENT_VIDEO_NOTES) == 2
    assert -1 not in runtime._RECENT_VIDEO_NOTES
    assert -2 in runtime._RECENT_VIDEO_NOTES
    assert -3 in runtime._RECENT_VIDEO_NOTES
