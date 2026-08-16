from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"marker not found in {path}: {old[:100]!r}")
    if text.count(old) != 1:
        raise SystemExit(f"marker not unique in {path}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# ------------------------------------------------------------------
# style_engine.py: short fuse for first two hostile turns, controlled
# escalation on 3rd/4th, never a 900-char hostile wall.
# ------------------------------------------------------------------
replace_once(
    "style_engine.py",
    "    character_state: str = \"normal\"\n",
    "    character_state: str = \"normal\"\n    hostile_streak: int = 0\n",
)
replace_once(
    "style_engine.py",
    "class ResponseLengthPlan:\n    category: str\n    min_chars: int\n    max_chars: int\n    target_chars: int\n",
    "class ResponseLengthPlan:\n    category: str\n    min_chars: int\n    max_chars: int\n    target_chars: int\n    conversation_mode: str = \"normal\"\n    hostile_streak: int = 0\n",
)
replace_once(
    "style_engine.py",
    '''    if ctx.conversation_mode in ("challenge", "hostile"):\n        return {\n            "micro": 0.34,\n            "short": 0.44,\n            "normal": 0.19,\n            "long": 0.03,\n        }\n''',
    '''    if ctx.conversation_mode == "hostile":\n        if ctx.hostile_streak >= 3:\n            # Третий-четвёртый подряд наезд: Яйцеслав может уже нормально\n            # развернуться, но это всё ещё злой ответ, а не эссе.\n            return {\n                "micro": 0.10,\n                "short": 0.34,\n                "normal": 0.56,\n                "long": 0.00,\n            }\n        # Первый-второй наезд: чаще естественный короткий посыл.\n        return {\n            "micro": 0.78,\n            "short": 0.22,\n            "normal": 0.00,\n            "long": 0.00,\n        }\n\n    if ctx.conversation_mode == "challenge":\n        return {\n            "micro": 0.55,\n            "short": 0.38,\n            "normal": 0.07,\n            "long": 0.00,\n        }\n''',
)
replace_once(
    "style_engine.py",
    '''def choose_response_length(\n    chat_id: int,\n''',
    '''def _range_for_context(\n    ctx: ResponseLengthContext,\n    category: str,\n) -> tuple[int, int]:\n    if ctx.conversation_mode == "hostile":\n        if ctx.hostile_streak >= 3:\n            return {\n                "micro": (25, 95),\n                "short": (80, 220),\n                "normal": (200, 450),\n                "long": (200, 450),\n            }[category]\n        return {\n            "micro": (12, 90),\n            "short": (55, 180),\n            "normal": (120, 220),\n            "long": (120, 220),\n        }[category]\n    return _LENGTH_RANGES[category]\n\n\ndef choose_response_length(\n    chat_id: int,\n''',
)
replace_once(
    "style_engine.py",
    '''    history = (\n        _LENGTH_HISTORY[chat_id]\n        if record\n        else deque(maxlen=5)\n    )\n    _apply_history_bias(weights, tuple(history))\n\n    category = _weighted_choice(weights, rng=rng)\n''',
    '''    history = (\n        _LENGTH_HISTORY[chat_id]\n        if record\n        else deque(maxlen=5)\n    )\n    # В конфликте естественнее несколько коротких ответов подряд, чем\n    # искусственное чередование micro -> short -> normal ради разнообразия.\n    use_history_bias = ctx.conversation_mode != "hostile"\n    if use_history_bias:\n        _apply_history_bias(weights, tuple(history))\n\n    category = _weighted_choice(weights, rng=rng)\n''',
)
replace_once(
    "style_engine.py",
    "    if history and category == history[-1]:\n",
    "    if use_history_bias and history and category == history[-1]:\n",
)
replace_once(
    "style_engine.py",
    "    min_chars, max_chars = _LENGTH_RANGES[category]\n",
    "    min_chars, max_chars = _range_for_context(ctx, category)\n",
)
replace_once(
    "style_engine.py",
    '''    return ResponseLengthPlan(\n        category=category,\n        min_chars=min_chars,\n        max_chars=max_chars,\n        target_chars=target_chars,\n    )\n''',
    '''    return ResponseLengthPlan(\n        category=category,\n        min_chars=min_chars,\n        max_chars=max_chars,\n        target_chars=target_chars,\n        conversation_mode=ctx.conversation_mode,\n        hostile_streak=ctx.hostile_streak,\n    )\n''',
)
replace_once(
    "style_engine.py",
    '''    return (\n        "\\n\\nДинамическая длина этого конкретного ответа:\\n"\n        f"Класс: {plan.category}; ориентир около {plan.target_chars} символов.\\n"\n        f"{rules[plan.category]}\\n"\n        "Это ориентир, а не обязанность добивать текст до числа символов."\n    )\n''',
    '''    hostile_rule = ""\n    if plan.conversation_mode == "hostile":\n        if plan.hostile_streak >= 3:\n            hostile_rule = (\n                "\\nЭто уже третий-четвёртый подряд наезд этого человека: можно развернуться "\n                "в злой ответ на 2–5 предложений, но максимум примерно 450 символов. "\n                "Не превращай разнос в лекцию."\n            )\n        else:\n            hostile_rule = (\n                "\\nЭто первый-второй подряд наезд: ответ должен быть особенно коротким. "\n                "Одна матерная фраза или короткий огрызок считается полноценным ответом; "\n                "после него остановись."\n            )\n\n    return (\n        "\\n\\nДинамическая длина этого конкретного ответа:\\n"\n        f"Класс: {plan.category}; ориентир около {plan.target_chars} символов.\\n"\n        f"{rules[plan.category]}\\n"\n        "Это ориентир, а не обязанность добивать текст до числа символов."\n        + hostile_rule\n    )\n''',
)

# ------------------------------------------------------------------
# voice_runtime.py: make a one-line profane sendoff explicitly valid.
# ------------------------------------------------------------------
replace_once(
    "voice_runtime.py",
    '''            "Если пользователь прямо оскорбил тебя, естественный вариант — просто коротко и матерно его отбрить/послать "\n            "одной фразой без шутки. Можно быть грубым, матерным и резким по смыслу, но после основного ответа остановись."\n''',
    '''            "Если пользователь прямо оскорбил тебя, естественный вариант — просто коротко и матерно его отбрить/послать "\n            "одной фразой без шутки. Ответ уровня «иди нахуй», «отъебись» или столь же короткий прямой посыл "\n            "сам по себе является ПОЛНЫМ ответом — не объясняй его, не добавляй второй абзац и не продолжай после него. "\n            "Можно быть грубым, матерным и резким по смыслу, но после основного ответа остановись."\n''',
)

# ------------------------------------------------------------------
# bot.py: wire per-user streak, cleanup, feedback diagnostics.
# ------------------------------------------------------------------
replace_once(
    "bot.py",
    "import humanizer_engine\n",
    "import humanizer_engine\nimport hostile_streak_engine\n",
)
replace_once(
    "bot.py",
    '''        conversation_mode = detect_conversation_mode(style_text)\n\n        resolved_intent, intent_confidence = intent.classify_intent(\n''',
    '''        conversation_mode = detect_conversation_mode(style_text)\n\n        hostile_streak = 0\n        if (\n            chat_id is not None\n            and user_id is not None\n            and chat_type in ("group", "supergroup")\n            and bot_was_mentioned\n        ):\n            hostile_streak = hostile_streak_engine.observe(\n                chat_id,\n                user_id,\n                hostile=(conversation_mode == "hostile"),\n            )\n\n        resolved_intent, intent_confidence = intent.classify_intent(\n''',
)
replace_once(
    "bot.py",
    '''                serious_topic=(conversation_mode == "serious"),\n                character_state=character_state,\n            ),\n''',
    '''                serious_topic=(conversation_mode == "serious"),\n                character_state=character_state,\n                hostile_streak=hostile_streak,\n            ),\n''',
)
replace_once(
    "bot.py",
    '''    stale_aggression_keys = aggression_engine.prune_stale_state(\n        max_age_seconds, now=now\n    )\n    stale_length_chats = style_engine.prune_stale_state(\n''',
    '''    stale_aggression_keys = aggression_engine.prune_stale_state(\n        max_age_seconds, now=now\n    )\n    stale_hostile_streaks = hostile_streak_engine.prune_stale_state(\n        max_age_seconds, now=now\n    )\n    stale_length_chats = style_engine.prune_stale_state(\n''',
)
replace_once(
    "bot.py",
    '''        "aggression_keys": stale_aggression_keys,\n        "length_chats": stale_length_chats,\n''',
    '''        "aggression_keys": stale_aggression_keys,\n        "hostile_streaks": stale_hostile_streaks,\n        "length_chats": stale_length_chats,\n''',
)
replace_once(
    "bot.py",
    '''        distinct_users = int(\n            connection.execute(\n                "SELECT COUNT(DISTINCT user_id) FROM chat_native_term_users WHERE chat_id = ?",\n                (chat_id,),\n            ).fetchone()[0]\n        )\n    adaptation = get_chat_feedback_adaptation_sync(chat_id)\n''',
    '''        distinct_users = int(\n            connection.execute(\n                "SELECT COUNT(DISTINCT user_id) FROM chat_native_term_users WHERE chat_id = ?",\n                (chat_id,),\n            ).fetchone()[0]\n        )\n        tracked_messages = int(\n            connection.execute(\n                "SELECT COUNT(*) FROM bot_response_feedback WHERE chat_id = ?",\n                (chat_id,),\n            ).fetchone()[0]\n        )\n    adaptation = get_chat_feedback_adaptation_sync(chat_id)\n''',
)
replace_once(
    "bot.py",
    '''        "observed_users": distinct_users,\n        "reacted_messages": int(adaptation.get("reacted_messages", 0)),\n''',
    '''        "observed_users": distinct_users,\n        "tracked_messages": tracked_messages,\n        "reacted_messages": int(adaptation.get("reacted_messages", 0)),\n''',
)
replace_once(
    "bot.py",
    '''        f"Кандидатов-термов: {status.get('candidate_terms', 0)}\\n"\n        f"Ответов с реакционной обратной связью: {status.get('reacted_messages', 0)}\\n"\n''',
    '''        f"Кандидатов-термов: {status.get('candidate_terms', 0)}\\n"\n        f"Отслеживаемых ответов Яйцеслава: {status.get('tracked_messages', 0)}\\n"\n        f"Ответов с реакционной обратной связью: {status.get('reacted_messages', 0)}\\n"\n''',
)
replace_once(
    "bot.py",
    '''    if updated:\n        adaptation_cache.invalidate("feedback", reaction.chat.id)\n''',
    '''    if updated:\n        adaptation_cache.invalidate("feedback", reaction.chat.id)\n        logging.info(\n            "Reaction feedback matched chat=%s message=%s score_delta=%.2f count_delta=%s",\n            reaction.chat.id,\n            reaction.message_id,\n            score_delta,\n            count_delta,\n        )\n    else:\n        logging.info(\n            "Reaction feedback received for untracked message chat=%s message=%s",\n            reaction.chat.id,\n            reaction.message_id,\n        )\n''',
)

# Permanent CI must compile the new engine.
replace_once(
    ".github/workflows/v2-ci.yml",
    "          chat_native_engine.py feedback_engine.py humanizer_engine.py adaptation_cache.py\n",
    "          chat_native_engine.py feedback_engine.py humanizer_engine.py adaptation_cache.py hostile_streak_engine.py\n",
)

# ------------------------------------------------------------------
# Regression tests for the exact live bug and requested rhythm.
# ------------------------------------------------------------------
Path("tests/test_hostile_brevity_runtime.py").write_text(
    '''import random\n\nimport bot\nimport style_engine\nimport voice_runtime\n\n\ndef test_first_two_hostile_turns_never_become_normal_or_long():\n    style_engine.reset_length_history()\n    for streak in (1, 2):\n        for seed in range(80):\n            plan = style_engine.choose_response_length(\n                9001,\n                style_engine.ResponseLengthContext(\n                    user_text="ты ебобо",\n                    conversation_mode="hostile",\n                    hostile_streak=streak,\n                ),\n                rng=random.Random(seed),\n                record=False,\n            )\n            assert plan.category in {"micro", "short"}\n            assert plan.max_chars <= 180\n\n\ndef test_third_fourth_hostile_turns_can_escalate_but_never_to_long_wall():\n    categories = set()\n    for streak in (3, 4):\n        for seed in range(120):\n            plan = style_engine.choose_response_length(\n                9002,\n                style_engine.ResponseLengthContext(\n                    user_text="да пошел ты еще раз",\n                    conversation_mode="hostile",\n                    hostile_streak=streak,\n                ),\n                rng=random.Random(seed),\n                record=False,\n            )\n            categories.add(plan.category)\n            assert plan.category != "long"\n            assert plan.max_chars <= 450\n    assert "normal" in categories\n\n\ndef test_hostile_length_instruction_distinguishes_short_fuse_and_escalation():\n    short_plan = style_engine.ResponseLengthPlan(\n        category="micro", min_chars=12, max_chars=90, target_chars=30,\n        conversation_mode="hostile", hostile_streak=1,\n    )\n    escalated_plan = style_engine.ResponseLengthPlan(\n        category="normal", min_chars=200, max_chars=450, target_chars=320,\n        conversation_mode="hostile", hostile_streak=3,\n    )\n    assert "Одна матерная фраза" in style_engine.build_length_instruction(short_plan)\n    assert "2–5 предложений" in style_engine.build_length_instruction(escalated_plan)\n\n\ndef test_plain_hostile_voice_instruction_allows_one_line_sendoff_and_stop():\n    class Rng:\n        @staticmethod\n        def random():\n            return 0.99\n        @staticmethod\n        def choice(seq):\n            return seq[0]\n\n    material = voice_runtime.choose_voice_material(\n        "blat", conversation_mode="hostile", roughness="high", rng=Rng()\n    )\n    instruction = voice_runtime.build_voice_instruction(material)\n    assert "иди нахуй" in instruction\n    assert "ПОЛНЫМ ответом" in instruction\n    assert "не продолжай" in instruction\n\n\ndef test_feedback_status_distinguishes_tracked_from_reacted(tmp_path, monkeypatch):\n    monkeypatch.setattr(bot, "STATS_DB_PATH", tmp_path / "feedback-status.db")\n    bot.initialize_stats_database()\n\n    trace = bot.feedback_engine.ResponseTrace(\n        chat_id=-100, chat_type="group", voice_pack="blat", humor_type="rough"\n    )\n    bot.store_bot_response_feedback_sync(-100, 77, trace)\n\n    status = bot.get_chat_native_learning_status_sync(-100)\n    assert status["tracked_messages"] == 1\n    assert status["reacted_messages"] == 0\n\n    assert bot.apply_bot_reaction_delta_sync(-100, 77, -1.2, 1)\n    status = bot.get_chat_native_learning_status_sync(-100)\n    assert status["tracked_messages"] == 1\n    assert status["reacted_messages"] == 1\n''',
    encoding="utf-8",
)

print("hostile/feedback patch applied")
