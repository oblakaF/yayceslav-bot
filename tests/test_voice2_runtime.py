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


def test_structured_call_uses_json_schema_and_sets_voice_override():
    captured = {}

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

    bot_module = SimpleNamespace(
        build_full_system_instruction=lambda *args, **kwargs: "SYSTEM",
        GEMINI_SEMAPHORE=asyncio.Semaphore(1),
        gemini_client=SimpleNamespace(aio=SimpleNamespace(models=FakeModels())),
        MODEL_NAME="test-model",
        types=SimpleNamespace(
            GenerateContentConfig=FakeGenerateContentConfig,
            ThinkingConfig=FakeThinkingConfig,
        ),
    )

    voice2_runtime._VOICE_REPLY_OVERRIDE.set(None)
    result = asyncio.run(
        voice2_runtime._structured_voice_decision(
            bot_module,
            [object(), "Прослушай сообщение пользователя"],
            {"chat_type": "private", "max_output_tokens": 320},
        )
    )

    assert '"answer": "Четыре."' in result
    config = captured["config"].kwargs
    assert config["response_mime_type"] == "application/json"
    assert config["response_schema"] is voice2_runtime.VoiceDecision
    assert voice2_runtime._VOICE_REPLY_OVERRIDE.get() is True
    voice2_runtime._VOICE_REPLY_OVERRIDE.set(None)
