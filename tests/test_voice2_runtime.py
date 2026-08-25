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


def test_non_search_decision_drops_control_query():
    decision = voice2_runtime._normalize_decision(
        voice2_runtime.VoiceDecision(
            transcript="объясни что такое резонанс",
            needs_search=False,
            search_query="лишний запрос",
            answer="Резонанс — это рост отклика около собственной частоты.",
        )
    )
    assert decision.search_query == ""
    assert decision.answer.startswith("Резонанс")


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
