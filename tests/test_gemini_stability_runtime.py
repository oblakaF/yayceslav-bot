import asyncio
from types import SimpleNamespace

import gemini_stability_runtime as stability
import thinking_engine
import voice2_runtime


class CapacityError(RuntimeError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def test_json_recovery_accepts_wrapped_object_and_quoted_braces():
    raw = 'Here is the JSON requested: {"answer":"скобка } внутри строки","ok":true} thanks'
    assert stability.extract_json_object(raw) == {
        "answer": "скобка } внутри строки",
        "ok": True,
    }


def test_json_recovery_rejects_truncated_object_instead_of_guessing():
    assert stability.extract_json_object('{"answer":"обрезалось') is None


def test_news_json_recovery_handles_model_preamble():
    parsed = stability.parse_news_comment_json(
        'Sure. {"tone":"negative","comment":"Ну опять приехали, классика жанра."}'
    )
    assert parsed == ("negative", "Ну опять приехали, классика жанра.")


def test_voice_schema_recovers_valid_json_wrapped_in_prose():
    stability.install_voice_json_recovery()
    raw = (
        'Here is the JSON requested:\n'
        '{"transcript":"скажи привет","needs_search":false,"search_query":"",'
        '"answer":"Привет.","wants_voice":false,"memory_summary":""}'
    )
    decision = voice2_runtime.VoiceDecision.model_validate_json(raw)
    assert decision.transcript == "скажи привет"
    assert decision.answer == "Привет."
    assert decision.needs_search is False


def test_capacity_detection_matches_real_503_and_429_shapes():
    assert stability.is_unavailable_503(
        CapacityError(503, "503 UNAVAILABLE: This model is currently experiencing high demand")
    )
    assert stability.is_capacity_error(CapacityError(429, "429 RESOURCE_EXHAUSTED quota"))
    assert not stability.is_capacity_error(CapacityError(500, "internal error"))


def test_adaptive_cooldown_escalates_30_60_120_and_resets_after_quiet_window(monkeypatch):
    monkeypatch.setattr(stability, "_failure_streak", 0)
    monkeypatch.setattr(stability, "_last_failure_epoch", 0.0)
    monkeypatch.setattr(stability, "_save_stability_state", lambda: None)
    monkeypatch.setattr(thinking_engine, "_save_router_state", lambda: None)

    clock = {"now": 1_000_000.0}
    monkeypatch.setattr(stability.time, "time", lambda: clock["now"])

    assert stability._adaptive_start_primary_cooldown() == 30 * 60
    clock["now"] += 31 * 60
    assert stability._adaptive_start_primary_cooldown() == 60 * 60
    clock["now"] += 61 * 60
    assert stability._adaptive_start_primary_cooldown() == 120 * 60
    clock["now"] += stability.FAILURE_STREAK_RESET_SECONDS + 1
    assert stability._adaptive_start_primary_cooldown() == 30 * 60


def test_primary_503_falls_back_to_31_in_same_api_call(monkeypatch):
    calls = []
    monkeypatch.setattr(thinking_engine, "_primary_blocked_until_epoch", 0.0)
    monkeypatch.setattr(stability, "_adaptive_start_primary_cooldown", lambda: 1800)

    async def original(model_self, *args, **kwargs):
        del model_self, args
        model = kwargs.get("model")
        calls.append(model)
        if model == thinking_engine.PRIMARY_MODEL:
            raise CapacityError(503, "503 UNAVAILABLE high demand")
        return SimpleNamespace(text="fallback ok", parsed=None, candidates=[])

    result = asyncio.run(
        stability.route_capacity_failure(
            original,
            object(),
            model=thinking_engine.PRIMARY_MODEL,
            contents="test",
        )
    )

    assert result.text == "fallback ok"
    assert calls == [thinking_engine.PRIMARY_MODEL, thinking_engine.FALLBACK_MODEL]


def test_both_models_capacity_limited_returns_quick_graceful_response(monkeypatch):
    calls = []
    monkeypatch.setattr(thinking_engine, "_primary_blocked_until_epoch", 0.0)

    def start_cooldown():
        thinking_engine._primary_blocked_until_epoch = stability.time.time() + 1800
        return 1800

    monkeypatch.setattr(stability, "_adaptive_start_primary_cooldown", start_cooldown)

    async def original(model_self, *args, **kwargs):
        del model_self, args
        calls.append(kwargs.get("model"))
        raise CapacityError(503, "503 UNAVAILABLE high demand")

    result = asyncio.run(
        stability.route_capacity_failure(
            original,
            object(),
            model=thinking_engine.PRIMARY_MODEL,
            contents="test",
            config=SimpleNamespace(response_schema=None),
        )
    )

    assert result.text == stability.CAPACITY_MESSAGE
    assert calls == [thinking_engine.PRIMARY_MODEL, thinking_engine.FALLBACK_MODEL]


def test_capacity_response_is_voice_schema_compatible():
    config = SimpleNamespace(response_schema=voice2_runtime.VoiceDecision)
    response = stability._capacity_response(
        {"config": config},
        CapacityError(503, "503 UNAVAILABLE"),
    )
    assert isinstance(response.parsed, voice2_runtime.VoiceDecision)
    assert response.parsed.answer == stability.CAPACITY_MESSAGE
    assert response.parsed.needs_search is False
