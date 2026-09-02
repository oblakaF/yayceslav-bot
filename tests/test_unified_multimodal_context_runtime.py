import asyncio
from types import SimpleNamespace

import unified_multimodal_context_runtime as runtime
import voice2_runtime
import voice_live_bridge_runtime


def setup_function():
    runtime._INSTALLED = False
    runtime._PREPARED_APPLICATION_IDS.clear()
    voice_live_bridge_runtime._VOICE_CONTEXT.clear()
    voice2_runtime._VIDEO_NOTE_MEMORY_SUMMARY.set("")


def test_text_memory_is_injected_into_next_voice_turn(monkeypatch):
    captured = {}

    async def fake_ask(contents, *args, **kwargs):
        captured.update(kwargs)
        return "ok"

    module = SimpleNamespace(
        ask_gemini=fake_ask,
        PRIVATE_MEMORY={100: object()},
        PRIVATE_MEMORY_SECONDS=900,
        build_memory_context=lambda memory, key, ttl: (
            "Вадим: сравнивали BMW M3 и Alfa Romeo\nЯйцеслав: взял бы Alfa"
        ),
    )
    monkeypatch.setattr(runtime.voice2_runtime, "_is_voice_decision_request", lambda contents: True)
    runtime._patch_voice_input_context(module)

    asyncio.run(
        module.ask_gemini(
            [object(), "voice control"],
            chat_id=100,
            chat_type="private",
            user_id=100,
        )
    )

    assert any("BMW M3" in line for line in captured["recent_messages"])
    assert any("взял бы Alfa" in line for line in captured["recent_messages"])


def test_voice_transcript_replaces_generic_placeholder_in_text_memory():
    remembered = []

    def fake_remember(memory, memory_id, role, text, ttl, cap, author=None):
        remembered.append((memory_id, role, text, author))

    module = SimpleNamespace(remember_message=fake_remember)
    voice_live_bridge_runtime._remember_voice_turn(
        100,
        "а почему именно эту машину?",
        "Потому что она живая и не стерильная.",
        speaker="Вадим",
    )
    runtime._patch_voice_memory_placeholders(module)
    module.remember_message({}, 100, "user", runtime._VOICE_PLACEHOLDER, 900, 40)

    assert remembered[0][2] == "[Голосовое: а почему именно эту машину?]"


def test_video_note_memory_combines_spoken_meaning_and_visual_summary():
    remembered = []

    def fake_remember(memory, memory_id, role, text, ttl, cap, author=None):
        remembered.append(text)

    module = SimpleNamespace(remember_message=fake_remember)
    voice_live_bridge_runtime._remember_voice_turn(
        -77,
        "смотри, он опять полез на шкаф",
        "Да, кот явно выбрал высоту.",
        speaker="Серега",
    )
    voice2_runtime._VIDEO_NOTE_MEMORY_SUMMARY.set("рыжий кот карабкается на высокий шкаф")
    runtime._patch_voice_memory_placeholders(module)
    module.remember_message({}, -77, "user", runtime._VIDEO_NOTE_PLACEHOLDER, 900, 30, "Серега")

    assert "видно: рыжий кот карабкается" in remembered[0]
    assert "сказано: смотри, он опять полез на шкаф" in remembered[0]
    assert voice2_runtime._VIDEO_NOTE_MEMORY_SUMMARY.get() == ""


def test_old_voice_turn_is_not_reused_as_current_semantics():
    voice_live_bridge_runtime._VOICE_CONTEXT[5] = [
        voice_live_bridge_runtime.VoiceContextTurn(
            timestamp=100.0,
            transcript="старая тема про концерт",
            answer="старый ответ",
            speaker="",
        )
    ]
    transcript, answer = runtime._latest_voice_semantics(
        5,
        now=100.0 + runtime.SEMANTIC_CAPTURE_MAX_AGE_SECONDS + 1,
    )
    assert transcript == ""
    assert answer == ""


def test_regular_video_prompt_requires_both_frames_and_audio():
    prompt = runtime._video_prompt("что он там сказал и что показывает?")
    assert "ПОСМОТРИ видимые кадры" in prompt
    assert "ПРОСЛУШАЙ аудиодорожку" in prompt
    assert "что он там сказал" in prompt
    assert "Не придумывай" in prompt


def test_video_exchange_writes_into_existing_group_memory():
    calls = []
    group_memory = {}

    def remember(memory, key, role, text, ttl, cap, author=None):
        calls.append((memory, key, role, text, author))

    module = SimpleNamespace(
        remember_message=remember,
        GROUP_MEMORY=group_memory,
        GROUP_MEMORY_SECONDS=900,
        GROUP_MEMORY_MAX_MESSAGES=30,
    )
    runtime._remember_exchange(
        module,
        chat_id=-10,
        chat_type="group",
        user_id=9,
        user_name="Серега",
        user_text="[Пользователь прислал видео] что тут происходит?",
        answer="Кот стащил пакет и убежал.",
    )

    assert calls[0][0] is group_memory
    assert calls[0][1] == -10
    assert calls[0][2] == "user"
    assert calls[0][4] == "Серега"
    assert calls[1][2] == "assistant"
    assert "Кот стащил пакет" in calls[1][3]


def test_video_handler_registration_is_idempotent():
    handlers = []
    application = SimpleNamespace(add_handler=lambda handler, group=0: handlers.append((handler, group)))

    runtime.prepare_application_runtime(application)
    runtime.prepare_application_runtime(application)

    assert len(handlers) == 1
    assert handlers[0][1] == runtime._HANDLER_GROUP
