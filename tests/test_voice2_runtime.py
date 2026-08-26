import asyncio
from types import SimpleNamespace

import voice2_runtime


def test_voice_request_detector_only_matches_control_prompt():
    assert voice2_runtime._is_voice_decision_request(
        [
            object(),
            'Прослушай сообщение пользователя. {"needs_search": false, "search_query": "", "answer": ""}',
        ]
    )
    assert not voice2_runtime._is_voice_decision_request(
        [object(), "Посмотри кружок и коротко прокомментируй его."]
    )


def test_video_note_request_detects_mp4_inline_part_only():
    video_part = SimpleNamespace(inline_data=SimpleNamespace(mime_type="video/mp4"))
    audio_part = SimpleNamespace(inline_data=SimpleNamespace(mime_type="audio/ogg"))

    assert voice2_runtime._is_video_note_request([video_part, "prompt"])
    assert not voice2_runtime._is_video_note_request([audio_part, "prompt"])
    assert not voice2_runtime._is_video_note_request("video/mp4")


def test_search_decision_recovers_query_from_ephemeral_transcript():
    decision = voice2_runtime._normalize_decision(
        voice2_runtime.VoiceDecision(
            transcript="проверь в интернете кто сейчас президент Франции",
            needs_search=True,
            search_query="",
            answer="это поле не должно уйти пользователю",
            wants_voice=True,
        )
    )
    assert decision.needs_search is True
    assert decision.search_query == "проверь в интернете кто сейчас президент Франции"
    assert decision.answer == ""
    assert decision.wants_voice is True
    assert decision.memory_summary == ""


def test_non_search_decision_drops_control_query():
    decision = voice2_runtime._normalize_decision(
        voice2_runtime.VoiceDecision(
            transcript="объясни что такое резонанс",
            needs_search=False,
            search_query="лишний запрос",
            answer="Резонанс — это рост отклика около собственной частоты.",
            memory_summary="это не должно сохраняться для обычного аудио",
        )
    )
    assert decision.search_query == ""
    assert decision.answer.startswith("Резонанс")
    assert decision.memory_summary == ""


def test_video_note_keeps_only_short_visual_memory_summary():
    decision = voice2_runtime._normalize_decision(
        voice2_runtime.VoiceDecision(
            transcript="смотри",
            needs_search=False,
            answer="Котята устроились царски.",
            memory_summary="[два котёнка лежат рядом под одеялом]",
        ),
        video_note=True,
    )

    assert decision.memory_summary == "два котёнка лежат рядом под одеялом"
    assert len(decision.memory_summary) <= 240


def test_explicit_voice_request_overrides_wrong_model_flag():
    decision = voice2_runtime._normalize_decision(
        voice2_runtime.VoiceDecision(
            transcript="Ответь мне голосом, сколько будет 17 умножить на 8?",
            needs_search=False,
            answer="136.",
            wants_voice=False,
        )
    )
    assert decision.wants_voice is True
    assert voice2_runtime._transcript_explicitly_requests_voice(
        "Голосом ответь, пожалуйста, сколько будет два плюс два"
    )
    assert not voice2_runtime._transcript_explicitly_requests_voice(
        "Я отправил голосовое сообщение про резонанс"
    )


def test_structured_call_uses_json_schema_profile_and_sets_voice_override():
    captured = {}
    instruction_kwargs = {}

    class FakeModels:
        async def generate_content(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                parsed=voice2_runtime.VoiceDecision(
                    transcript="ответь голосом сколько будет два плюс два",
                    needs_search=False,
                    search_query="",
                    answer="Четыре.",
                    wants_voice=True,
                ),
                text="",
            )

    class FakeGenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeThinkingConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    async def get_member_profile(chat_id, user_id):
        assert (chat_id, user_id) == (-100, 42)
        return {"reputation": 17}

    def build_instruction(*args, **kwargs):
        instruction_kwargs.update(kwargs)
        return "SYSTEM"

    bot_module = SimpleNamespace(
        build_full_system_instruction=build_instruction,
        get_member_profile=get_member_profile,
        GEMINI_SEMAPHORE=asyncio.Semaphore(1),
        gemini_client=SimpleNamespace(aio=SimpleNamespace(models=FakeModels())),
        MODEL_NAME="test-model",
        types=SimpleNamespace(
            GenerateContentConfig=FakeGenerateContentConfig,
            ThinkingConfig=FakeThinkingConfig,
        ),
    )

    async def run_in_same_context():
        voice2_runtime._VOICE_REPLY_OVERRIDE.set(None)
        result = await voice2_runtime._structured_voice_decision(
            bot_module,
            [object(), "Прослушай сообщение пользователя"],
            {
                "chat_type": "group",
                "chat_id": -100,
                "user_id": 42,
                "max_output_tokens": 320,
            },
        )
        override = voice2_runtime._VOICE_REPLY_OVERRIDE.get()
        voice2_runtime._VOICE_REPLY_OVERRIDE.set(None)
        return result, override

    result, override = asyncio.run(run_in_same_context())

    assert '"answer": "Четыре."' in result
    assert instruction_kwargs["member_profile"] == {"reputation": 17}
    config = captured["config"].kwargs
    assert config["response_mime_type"] == "application/json"
    assert config["response_schema"] is voice2_runtime.VoiceDecision
    assert override is True


def test_structured_video_note_explicitly_watches_frames_and_captures_visual_memory():
    captured = {}

    class FakeModels:
        async def generate_content(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                parsed=voice2_runtime.VoiceDecision(
                    transcript="",
                    needs_search=False,
                    answer="Котята кайфуют под одеялом.",
                    memory_summary="два котёнка лежат рядом под одеялом",
                ),
                text="",
            )

    class FakeGenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeThinkingConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    instructions = []

    def build_instruction(*args, **kwargs):
        instructions.append(args[0])
        return "SYSTEM"

    bot_module = SimpleNamespace(
        build_full_system_instruction=build_instruction,
        GEMINI_SEMAPHORE=asyncio.Semaphore(1),
        gemini_client=SimpleNamespace(aio=SimpleNamespace(models=FakeModels())),
        MODEL_NAME="test-model",
        types=SimpleNamespace(
            GenerateContentConfig=FakeGenerateContentConfig,
            ThinkingConfig=FakeThinkingConfig,
        ),
    )
    video_part = SimpleNamespace(inline_data=SimpleNamespace(mime_type="video/mp4"))

    async def run():
        voice2_runtime._VIDEO_NOTE_MEMORY_SUMMARY.set("")
        result = await voice2_runtime._structured_voice_decision(
            bot_module,
            [video_part, "Прослушай сообщение пользователя"],
            {"chat_type": "group", "chat_id": -100, "user_id": 42},
        )
        summary = voice2_runtime._VIDEO_NOTE_MEMORY_SUMMARY.get()
        voice2_runtime._VIDEO_NOTE_MEMORY_SUMMARY.set("")
        return result, summary

    result, summary = asyncio.run(run())
    system_instruction = captured["config"].kwargs["system_instruction"]

    assert '"memory_summary": "два котёнка лежат рядом под одеялом"' in result
    assert summary == "два котёнка лежат рядом под одеялом"
    assert "WATCH the visible frames and LISTEN" in system_instruction
    assert "If there is no speech, still understand" in system_instruction
    assert "Do not claim that you cannot see the video" in system_instruction
    assert instructions == ["Прослушай сообщение пользователя"]


def test_video_note_memory_bridge_replaces_only_generic_ram_marker_once():
    calls = []

    def remember(*args, **kwargs):
        calls.append((args, kwargs))

    module = SimpleNamespace(remember_message=remember)
    voice2_runtime._install_video_note_memory_bridge(module)
    voice2_runtime._VIDEO_NOTE_MEMORY_SUMMARY.set("два котёнка лежат под одеялом")

    module.remember_message(
        object(),
        -100,
        "user",
        "[Пользователь отправил видео-кружок]",
        900,
        30,
        "Серега",
    )
    module.remember_message(
        object(),
        -100,
        "assistant",
        "Котята кайфуют.",
        900,
        30,
    )

    assert calls[0][0][3] == "[Видео-кружок: два котёнка лежат под одеялом]"
    assert calls[1][0][3] == "Котята кайфуют."
    assert voice2_runtime._VIDEO_NOTE_MEMORY_SUMMARY.get() == ""


def test_voice_resolver_guard_suppresses_malformed_or_empty_control_json():
    calls = []

    async def original(update, raw_answer, *, user_settings):
        calls.append(raw_answer)
        return "NORMAL"

    module = SimpleNamespace(_resolve_voice_search_answer=original)
    voice2_runtime._install_voice_resolver_guard(module)

    malformed = asyncio.run(
        module._resolve_voice_search_answer(
            object(),
            '{"needs_search": false, "search_query": ""',
            user_settings=None,
        )
    )
    empty_answer = asyncio.run(
        module._resolve_voice_search_answer(
            object(),
            '{"needs_search": false, "search_query": "", "answer": ""}',
            user_settings=None,
        )
    )
    normal = asyncio.run(
        module._resolve_voice_search_answer(
            object(),
            "обычный ответ",
            user_settings=None,
        )
    )

    assert "служебный ответ" in malformed
    assert "не сформировала ответ" in empty_answer
    assert normal == "NORMAL"
    assert calls == ["обычный ответ"]


def test_voice_resolver_restores_explicit_voice_override_from_payload():
    async def original(update, raw_answer, *, user_settings):
        return "136."

    module = SimpleNamespace(_resolve_voice_search_answer=original)
    voice2_runtime._install_voice_resolver_guard(module)

    async def run():
        voice2_runtime._VOICE_REPLY_OVERRIDE.set(None)
        answer = await module._resolve_voice_search_answer(
            object(),
            '{"transcript":"Ответь мне голосом, сколько будет 17 умножить на 8?",'
            '"needs_search":false,"search_query":"","answer":"136.","wants_voice":false}',
            user_settings=None,
        )
        override = voice2_runtime._VOICE_REPLY_OVERRIDE.get()
        voice2_runtime._VOICE_REPLY_OVERRIDE.set(None)
        return answer, override

    answer, override = asyncio.run(run())
    assert answer == "136."
    assert override is True
