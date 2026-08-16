from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"marker mismatch {path}: count={text.count(old)} old={old[:100]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1) Real live-chat insults/complaints must actually enter conflict mode.
replace_once(
    "personality.py",
    '''CHALLENGE_RE = re.compile(\n    r"(?:"\n    r"ч[её]\\s+так\\s+дерзко|"\n    r"почему\\s+хамишь|"\n    r"ты\\s+ч[её]\\s+хамишь|"\n    r"полегче|"\n    r"нормально\\s+разговаривай"\n    r")",\n    re.IGNORECASE,\n)\n''',
    '''CHALLENGE_RE = re.compile(\n    r"(?:"\n    r"ч[её]\\s+так\\s+дерзко|"\n    r"почему\\s+хамишь|"\n    r"ты\\s+ч[её]\\s+хамишь|"\n    r"полегче|"\n    r"нормально\\s+разговаривай|"\n    r"душн\\w*|"\n    r"простын\\w*|"\n    r"много\\s+текста|"\n    r"слишком\\s+длинн\\w*|"\n    r"короче\\s+отвечай|"\n    r"не\\s+пиши\\s+столько"\n    r")",\n    re.IGNORECASE,\n)\n''',
)
replace_once(
    "personality.py",
    '''    r"^\\s*(?:"\n    r"соси|"\n    r"заткнись|"\n    r"иди\\s+нах|"\n    r"пош[её]л\\s+нах"\n    r")\\b|"\n''',
    '''    r"^\\s*(?:"\n    r"соси|"\n    r"заткнись|"\n    r"сука|"\n    r"сучка|"\n    r"еблан\\w*|"\n    r"долбо[её]б\\w*|"\n    r"заебал\\w*|"\n    r"пиздабол\\w*|"\n    r"иди\\s+нах|"\n    r"пош[её]л\\s+нах"\n    r")\\b|"\n    r"\\b(?:нахуй|на\\s+хуй)\\b|"\n''',
)

# 2) Humanizer gets a raw-input fallback and smaller conflict envelopes.
replace_once(
    "humanizer_engine.py",
    '''_CYRILLIC_WORD_RE = re.compile(r"\\b[а-яё]{5,12}\\b", re.IGNORECASE)\n''',
    '''_CYRILLIC_WORD_RE = re.compile(r"\\b[а-яё]{5,12}\\b", re.IGNORECASE)\n_CONFLICT_INPUT_RE = re.compile(\n    r"(?:"\n    r"\\b(?:сука|сучка|еблан\\w*|долбо[её]б\\w*|заебал\\w*|пиздабол\\w*)\\b|"\n    r"\\b(?:нахуй|на\\s+хуй)\\b|"\n    r"\\bдушн\\w*\\b|"\n    r"\\bпростын\\w*\\b|"\n    r"много\\s+текста|слишком\\s+длинн\\w*|короче\\s+отвечай|не\\s+пиши\\s+столько"\n    r")",\n    re.IGNORECASE,\n)\n''',
)
replace_once(
    "humanizer_engine.py",
    '''def _first_compact_sentence(text: str, limit: int = 190) -> str:\n''',
    '''def _looks_like_conflict(user_text: str) -> bool:\n    return bool(_CONFLICT_INPUT_RE.search(user_text or ""))\n\n\ndef _lazy_eligible_request(user_text: str, trace) -> bool:\n    if _looks_like_conflict(user_text):\n        return False\n    intent_name = getattr(trace, "message_intent", "unknown") if trace else "unknown"\n    # "Лень" — редкий прикол только на реальном простом вопросе,\n    # а не на междометии, оскорблении или обычной реплике чата.\n    return intent_name == "question" and len((user_text or "").strip()) <= 120\n\n\ndef _first_compact_sentence(text: str, limit: int = 190) -> str:\n''',
)
replace_once(
    "humanizer_engine.py",
    '''    compact_conflict = (\n        mode == "challenge"\n        or (mode == "hostile" and int(hostile_streak) < 3)\n    )\n    if compact_conflict and not important:\n        max_chars = 125 if mode == "hostile" else 155\n        pieces = _compact_conflict_text(clean, max_chars=max_chars, max_sentences=2)\n''',
    '''    raw_conflict = _looks_like_conflict(user_text)\n    compact_conflict = raw_conflict or mode in {"challenge", "hostile"}\n    if compact_conflict and not important:\n        escalated = mode == "hostile" and int(hostile_streak) >= 3\n        if escalated:\n            max_chars = 220\n            max_sentences = 3\n        else:\n            max_chars = 95 if (raw_conflict or mode == "hostile") else 110\n            max_sentences = 2\n        pieces = _compact_conflict_text(\n            clean,\n            max_chars=max_chars,\n            max_sentences=max_sentences,\n        )\n''',
)
replace_once(
    "humanizer_engine.py",
    '''    if not important:\n        roll = rng.random()\n        if roll < LAZY_REFUSAL_CHANCE:\n''',
    '''    if not important and _lazy_eligible_request(user_text, trace):\n        roll = rng.random()\n        if roll < LAZY_REFUSAL_CHANCE:\n''',
)

# 3) Default persona is aggressive; explicit calm/friendly settings disable it.
replace_once(
    "bot.py",
    '''        conversation_mode = detect_conversation_mode(style_text)\n\n        hostile_streak = 0\n''',
    '''        conversation_mode = detect_conversation_mode(style_text)\n\n        character_name = str(settings.get("character", "classic"))\n        response_style_name = str(settings.get("response_style", "bold"))\n        roughness_name = str(settings.get("roughness", "medium"))\n        default_aggressive = (\n            conversation_mode != "serious"\n            and character_name not in {"calm", "professor"}\n            and response_style_name != "serious"\n            and roughness_name != "low"\n        )\n        if default_aggressive:\n            if chat_type in ("group", "supergroup"):\n                current_instruction += (\n                    "\\n\\nРЕЖИМ ПО УМОЛЧАНИЮ В ГРУППЕ: агрессивный Яйцеслав. "\n                    "Не изображай вежливого ассистента: отвечай дерзко, уверенно, "\n                    "можешь материться и огрызаться. На полезный вопрос всё равно дай "\n                    "полезный ответ; агрессия — это характер, а не повод скрывать факты. "\n                    "В сраче ценятся короткость и хлёсткость, а не лекции."\n                )\n            else:\n                current_instruction += (\n                    "\\n\\nХАРАКТЕР ПО УМОЛЧАНИЮ: агрессивный Яйцеслав. "\n                    "Можно быть дерзким и материться, но полезный ответ остаётся полезным. "\n                    "Не превращай обычный ответ в травлю или бессмысленную ругань."\n                )\n\n        hostile_streak = 0\n''',
)

# 4) Permanent regressions for the exact live failures.
Path("tests/test_conflict_detection_lazy_gate.py").write_text(
    '''import random\n\nimport bot\nimport feedback_engine\nimport humanizer_engine\nimport personality\n\n\ndef _trace(mode="normal", intent_name="group_banter"):\n    return feedback_engine.ResponseTrace(\n        chat_id=1,\n        chat_type="group",\n        conversation_mode=mode,\n        message_intent=intent_name,\n    )\n\n\ndef test_live_short_insults_are_hostile():\n    for text in ("Сучка", "еблан", "долбоеб", "нахуй мне гугл если ты сучка"):\n        assert personality.detect_conversation_mode(text) == "hostile"\n\n\ndef test_live_wall_of_text_complaints_are_challenge():\n    for text in ("ебать опять простыня", "душный хуй", "много текста", "короче отвечай"):\n        assert personality.detect_conversation_mode(text) in {"challenge", "hostile"}\n\n\ndef test_raw_conflict_is_compacted_even_if_trace_was_wrongly_normal():\n    long_answer = (\n        "Гугл тебе затем, чтобы ты мысли формулировать научился. "\n        "А теперь начинается второй абзац с ненужной лекцией про аргументы и воспитание. "\n        "И третий абзац тоже не нужен."\n    )\n    plan = humanizer_engine.humanize_reply(\n        long_answer,\n        user_text="нахуй мне гугл если ты сучка",\n        trace=_trace("normal", "group_banter"),\n        rng=random.Random(3),\n    )\n    assert len(" ".join(plan.messages)) <= 95\n    assert "третий абзац" not in " ".join(plan.messages)\n\n\ndef test_lazy_never_fires_on_insult_even_with_zero_rng():\n    class ZeroRng:\n        def random(self):\n            return 0.0\n        def uniform(self, a, b):\n            return a\n        def choice(self, seq):\n            return seq[0]\n\n    plan = humanizer_engine.humanize_reply(\n        "Сам ты сучка.",\n        user_text="сучка",\n        trace=_trace("normal", "group_banter"),\n        rng=ZeroRng(),\n    )\n    assert "гугл" not in " ".join(plan.messages).lower()\n    assert not plan.effect.startswith("lazy")\n\n\ndef test_lazy_is_still_possible_on_real_small_question():\n    class ZeroRng:\n        def random(self):\n            return 0.0\n        def uniform(self, a, b):\n            return a\n        def choice(self, seq):\n            return seq[0]\n\n    plan = humanizer_engine.humanize_reply(\n        "Потому что так быстрее.",\n        user_text="почему так?",\n        trace=_trace("normal", "question"),\n        rng=ZeroRng(),\n    )\n    assert plan.effect == "lazy_refusal"\n\n\ndef test_default_aggressive_instruction_in_group_and_private():\n    group_instruction = bot.build_full_system_instruction(\n        "привет",\n        {"character": "classic", "response_style": "bold", "roughness": "high", "response_length": "normal"},\n        chat_type="group",\n    )\n    assert "РЕЖИМ ПО УМОЛЧАНИЮ В ГРУППЕ: агрессивный Яйцеслав" in group_instruction\n\n    private_instruction = bot.build_full_system_instruction(\n        "привет",\n        {"character": "classic", "response_style": "bold", "roughness": "high", "response_length": "normal"},\n        chat_type="private",\n    )\n    assert "ХАРАКТЕР ПО УМОЛЧАНИЮ: агрессивный Яйцеслав" in private_instruction\n\n\ndef test_calm_setting_disables_default_aggressive_layer():\n    instruction = bot.build_full_system_instruction(\n        "привет",\n        {"character": "calm", "response_style": "normal", "roughness": "low", "response_length": "normal"},\n        chat_type="group",\n    )\n    assert "РЕЖИМ ПО УМОЛЧАНИЮ В ГРУППЕ: агрессивный Яйцеслав" not in instruction\n''',
    encoding="utf-8",
)
