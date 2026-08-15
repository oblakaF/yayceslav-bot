from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0 and new in text:
        return
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_stateless_v2_fallbacks() -> None:
    replace_once(
        "style_engine.py",
        '''    history = _LENGTH_HISTORY[chat_id]\n    _apply_history_bias(weights, tuple(history))\n''',
        '''    history = (\n        _LENGTH_HISTORY[chat_id]\n        if record\n        else deque(maxlen=5)\n    )\n    _apply_history_bias(weights, tuple(history))\n''',
        "stateless length history",
    )

    replace_once(
        "humor_engine.py",
        '''def decide_humor(\n    ctx: HumorContext,\n    chat_id: int,\n    tracker: RepetitionTracker = REPETITION_TRACKER,\n) -> HumorDecision:\n''',
        '''def decide_humor(\n    ctx: HumorContext,\n    chat_id: int,\n    tracker: RepetitionTracker = REPETITION_TRACKER,\n    *,\n    remember_type: bool = True,\n) -> HumorDecision:\n''',
        "humor remember type parameter",
    )
    replace_once(
        "humor_engine.py",
        '''    candidates = _eligible_humor_types(ctx)\n    last_type = LAST_HUMOR_TYPE.get(chat_id)\n\n    if last_type and last_type in candidates and len(candidates) > 1:\n        candidates = [t for t in candidates if t != last_type]\n\n    humor_type = random.choice(candidates)\n    LAST_HUMOR_TYPE[chat_id] = humor_type\n''',
        '''    candidates = _eligible_humor_types(ctx)\n    last_type = (\n        LAST_HUMOR_TYPE.get(chat_id)\n        if remember_type\n        else None\n    )\n\n    if last_type and last_type in candidates and len(candidates) > 1:\n        candidates = [t for t in candidates if t != last_type]\n\n    humor_type = random.choice(candidates)\n    if remember_type:\n        LAST_HUMOR_TYPE[chat_id] = humor_type\n''',
        "stateless humor type",
    )

    replace_once(
        "bot.py",
        '''            response_preference=str(settings.get("response_length", "normal")),\n                serious_topic=(conversation_mode == "serious"),\n                character_state=character_state,\n            ),\n        )\n''',
        '''            response_preference=str(settings.get("response_length", "normal")),\n                serious_topic=(conversation_mode == "serious"),\n                character_state=character_state,\n            ),\n            record=(chat_id is not None),\n        )\n''',
        "disable global length memory without chat",
    )

    old = '''        tracker_chat_id = chat_id if chat_id is not None else 0\n\n        if conversation_mode == "hostile":\n            humor_decision = humor_engine.decide_banter(\n                humor_ctx, tracker_chat_id\n            )\n        else:\n            humor_decision = humor_engine.decide_humor(\n                humor_ctx, tracker_chat_id\n            )\n'''
    new = '''        if chat_id is None:\n            # Stateless path: never reuse synthetic key 0 between unrelated\n            # commands/users. Local tracker dies with this request.\n            humor_tracker = humor_engine.RepetitionTracker(maxlen=20)\n            tracker_chat_id = 0\n            remember_humor_type = False\n        else:\n            humor_tracker = humor_engine.REPETITION_TRACKER\n            tracker_chat_id = chat_id\n            remember_humor_type = True\n\n        if conversation_mode == "hostile":\n            humor_decision = humor_engine.decide_banter(\n                humor_ctx,\n                tracker_chat_id,\n                tracker=humor_tracker,\n            )\n        else:\n            humor_decision = humor_engine.decide_humor(\n                humor_ctx,\n                tracker_chat_id,\n                tracker=humor_tracker,\n                remember_type=remember_humor_type,\n            )\n'''
    replace_once("bot.py", old, new, "stateless humor without chat")


def patch_dead_v2_wires() -> None:
    replace_once(
        "bot.py",
        '''    HOSTILE_RE,\n    build_system_instruction,\n    build_v2_base_instruction,\n''',
        '''    HOSTILE_RE,\n    build_v2_base_instruction,\n''',
        "remove unused V1 prompt import",
    )

    replace_once(
        "social_engine.py",
        '''\ndef familiarity_humor_bonus(level: int) -> float:\n    """Небольшой бонус к фамильярности, не приказ обязательно шутить."""\n    if level >= 4:\n        return 0.10\n    if level >= 3:\n        return 0.07\n    if level >= 2:\n        return 0.04\n    if level >= 1:\n        return 0.02\n    return 0.0\n\n''',
        '''\n''',
        "remove unused familiarity bonus",
    )


def patch_gemini_token_retry() -> None:
    marker = '''async def ask_gemini(\n'''
    helper = '''def _gemini_finish_reason_name(response: Any) -> str:\n    candidates = getattr(response, "candidates", None) or []\n    if not candidates:\n        return ""\n    reason = getattr(candidates[0], "finish_reason", None)\n    if reason is None:\n        return ""\n    name = getattr(reason, "name", None)\n    return str(name or reason).upper()\n\n\ndef _gemini_hit_max_tokens(response: Any) -> bool:\n    return "MAX_TOKENS" in _gemini_finish_reason_name(response)\n\n\ndef _next_gemini_token_budget(current: int) -> int:\n    # Не раздуваем первый запрос. Увеличиваем только после реального\n    # finish_reason=MAX_TOKENS, максимум до 2048 для чатовых команд.\n    return min(2048, max(512, current * 2))\n\n\n'''
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if "def _gemini_hit_max_tokens(" not in text:
        if text.count(marker) != 1:
            raise SystemExit("ask_gemini marker mismatch")
        p.write_text(text.replace(marker, helper + marker, 1), encoding="utf-8")

    replace_once(
        "bot.py",
        '''    last_error: Exception | None = None\n\n    for attempt in range(1, 4):\n''',
        '''    last_error: Exception | None = None\n    request_token_budget = max_output_tokens\n\n    for attempt in range(1, 4):\n''',
        "initialize adaptive token budget",
    )
    replace_once(
        "bot.py",
        '''                            max_output_tokens=max_output_tokens,\n''',
        '''                            max_output_tokens=request_token_budget,\n''',
        "use adaptive token budget",
    )
    replace_once(
        "bot.py",
        '''            answer = (\n                response.text\n                or ""\n            ).strip()\n\n            if answer:\n                return answer\n\n            return (\n                "Нейронка ничего не выдала. "\n                "Переформулируй вопрос, гений."\n            )\n''',
        '''            answer = (\n                response.text\n                or ""\n            ).strip()\n\n            hit_max_tokens = _gemini_hit_max_tokens(response)\n            if (\n                hit_max_tokens\n                and attempt < 3\n                and request_token_budget < 2048\n            ):\n                next_budget = _next_gemini_token_budget(\n                    request_token_budget\n                )\n                logging.info(\n                    "Gemini упёрся в MAX_TOKENS (%s); повтор с бюджетом %s",\n                    request_token_budget,\n                    next_budget,\n                )\n                request_token_budget = next_budget\n                continue\n\n            if answer:\n                return answer\n\n            return (\n                "Нейронка ничего не выдала. "\n                "Переформулируй вопрос, гений."\n            )\n''',
        "retry max tokens before returning",
    )


def patch_readme() -> None:
    p = Path("README.md")
    text = p.read_text(encoding="utf-8")
    text = text.replace(
        "Модель Gemini — одна, `gemini-3.1-flash-lite` (Free Tier), задаётся через `MODEL_NAME` в `bot.py`.\n",
        "Модель Gemini — одна, `gemini-3.6-flash`, задаётся через `MODEL_NAME` в `bot.py`; для V2 используется `thinking_level=\"medium\"`.\n",
    )
    text = text.replace(
        "Каждое соединение открывается через `get_db_connection()`, которая включает\n`PRAGMA journal_mode=WAL` и `PRAGMA foreign_keys=ON`. Таймаут блокировки (аналог\n`PRAGMA busy_timeout`) уже обеспечивается параметром `timeout=30` при подключении.\n",
        "Каждое соединение открывается через `get_db_connection()`, которая включает\n`PRAGMA journal_mode=WAL` и `PRAGMA foreign_keys=ON`. Таймаут блокировки (аналог\n`PRAGMA busy_timeout`) обеспечивается параметром `timeout=30`, а context manager\nпосле commit/rollback теперь гарантированно закрывает SQLite-соединение.\n",
    )
    obsolete = '''- `/fact_or_bayan` пока рассуждает силами самой модели, не обращаясь к существующему\n  веб-поиску (`services`-модуля для поиска ещё нет, есть только функции в `bot.py`) —\n  разумное развитие, но не сделано в этом заходе.\n'''
    text = text.replace(obsolete, "")
    if "gemini-3.1-flash-lite" in text:
        raise SystemExit("README still contains old Gemini model")
    p.write_text(text, encoding="utf-8")


def write_tests() -> None:
    Path("tests/test_v2_final_audit_cleanup.py").write_text(
        '''from pathlib import Path\nfrom types import SimpleNamespace\n\nimport bot\nimport humor_engine\nimport style_engine\n\n\ndef test_no_chat_id_does_not_create_length_key_zero():\n    style_engine.reset_length_history()\n    bot.build_full_system_instruction("обычный вопрос", chat_id=None, user_id=None)\n    assert 0 not in style_engine._LENGTH_HISTORY\n    assert 0 not in style_engine._LENGTH_LAST_SEEN\n\n\ndef test_no_chat_id_does_not_create_humor_key_zero():\n    humor_engine.REPETITION_TRACKER._history.clear()\n    humor_engine.REPETITION_TRACKER._last_touched.clear()\n    humor_engine.LAST_HUMOR_TYPE.clear()\n    for _ in range(30):\n        bot.build_full_system_instruction(\n            "ну давай поговорим смешно", chat_id=None, user_id=None\n        )\n    assert 0 not in humor_engine.REPETITION_TRACKER._history\n    assert 0 not in humor_engine.REPETITION_TRACKER._last_touched\n    assert 0 not in humor_engine.LAST_HUMOR_TYPE\n\n\ndef test_gemini_finish_reason_detection_is_generic():\n    response = SimpleNamespace(\n        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="MAX_TOKENS"))]\n    )\n    assert bot._gemini_hit_max_tokens(response)\n    assert bot._next_gemini_token_budget(100) == 512\n    assert bot._next_gemini_token_budget(512) == 1024\n    assert bot._next_gemini_token_budget(1500) == 2048\n\n\ndef test_readme_names_current_model_only():\n    readme = Path("README.md").read_text(encoding="utf-8")\n    assert "gemini-3.6-flash" in readme\n    assert "gemini-3.1-flash-lite" not in readme\n\n\ndef test_bot_does_not_import_unused_v1_system_instruction():\n    source = Path("bot.py").read_text(encoding="utf-8")\n    import_block = source[source.index("from personality import ("):source.index(")", source.index("from personality import ("))]\n    assert "build_system_instruction" not in import_block\n\ndef test_removed_familiarity_bonus_is_not_dead_api():\n    import social_engine\n    assert not hasattr(social_engine, "familiarity_humor_bonus")\n''',
        encoding="utf-8",
    )


def main() -> None:
    patch_stateless_v2_fallbacks()
    patch_dead_v2_wires()
    patch_gemini_token_retry()
    patch_readme()
    write_tests()
    print("V2 final audit cleanup applied.")


if __name__ == "__main__":
    main()
