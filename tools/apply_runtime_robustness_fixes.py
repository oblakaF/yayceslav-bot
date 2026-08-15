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


def patch_sqlite_closing() -> None:
    replace_once(
        "bot.py",
        '''STATS_DB_PATH = DATA_DIR / "yayceslav_stats.db"\n\n\ndef get_db_connection(\n''',
        '''STATS_DB_PATH = DATA_DIR / "yayceslav_stats.db"\n\n\nclass ClosingSQLiteConnection(sqlite3.Connection):\n    """sqlite3 context manager с обязательным close() после commit/rollback."""\n\n    def __exit__(self, exc_type, exc, tb):\n        try:\n            return super().__exit__(exc_type, exc, tb)\n        finally:\n            self.close()\n\n\ndef get_db_connection(\n''',
        "closing sqlite connection class",
    )
    replace_once(
        "bot.py",
        '''    connection = sqlite3.connect(\n        db_path,\n        timeout=timeout,\n    )\n''',
        '''    connection = sqlite3.connect(\n        db_path,\n        timeout=timeout,\n        factory=ClosingSQLiteConnection,\n    )\n''',
        "sqlite closing factory",
    )


def patch_hard_mode_reservations() -> None:
    replace_once(
        "bot.py",
        '''    ):\n        await update.message.reply_text(\n            trigger_reply\n        )\n\n        context.chat_data[\n            "hard_last_trigger_reply"\n        ] = now\n        TRIGGER_REPLY_LAST_BY_USER[trigger_user_key] = now\n''',
        '''    ):\n        # Резервируем cooldown ДО сетевого await: второй concurrent update\n        # уже увидит занятый слот и не отправит дубль.\n        context.chat_data[\n            "hard_last_trigger_reply"\n        ] = now\n        TRIGGER_REPLY_LAST_BY_USER[trigger_user_key] = now\n\n        await update.message.reply_text(\n            trigger_reply\n        )\n''',
        "reserve trigger cooldown before await",
    )

    replace_once(
        "bot.py",
        '''        try:\n            await update.message.set_reaction(\n''',
        '''        # Та же защита от concurrent_updates(8): резервируем\n        # реакционный cooldown до Telegram API await.\n        context.chat_data[\n            "hard_last_reaction"\n        ] = now\n\n        try:\n            await update.message.set_reaction(\n''',
        "reserve reaction cooldown before await",
    )
    replace_once(
        "bot.py",
        '''            context.chat_data[\n                "hard_last_reaction"\n            ] = now\n            reacted_to_this_message = True\n''',
        '''            reacted_to_this_message = True\n''',
        "remove post-await reaction reservation",
    )

    replace_once(
        "bot.py",
        '''        if drop_decision.active and drop_decision.text:\n            await update.message.reply_text(drop_decision.text)\n\n            context.chat_data[\n                "hard_last_random_reply"\n            ] = now\n            record_group_random_reply(chat_id, now)\n''',
        '''        if drop_decision.active and drop_decision.text:\n            # Резервируем слот до await, иначе два апдейта могут пройти\n            # group_random_reply_allowed одновременно.\n            context.chat_data[\n                "hard_last_random_reply"\n            ] = now\n            record_group_random_reply(chat_id, now)\n\n            await update.message.reply_text(drop_decision.text)\n''',
        "reserve random reply before await",
    )

    replace_once(
        "bot.py",
        '''    GROUP_IGNORED_STREAK[chat_id] = 0\n''',
        '''    GROUP_IGNORED_STREAK.pop(chat_id, None)\n''',
        "do not retain zero engagement entries",
    )


def patch_memory_order() -> None:
    replace_once(
        "bot.py",
        '''        # Группа: память разговора за последние пять минут\n        elif (\n''',
        '''            # Текущее сообщение фиксируем ДО ожидания Gemini. Тогда\n            # следующий concurrent update этого пользователя уже увидит его\n            # в контексте, даже если первый ответ ещё генерируется.\n            remember_message(\n                PRIVATE_MEMORY,\n                private_user_id,\n                "user",\n                user_text,\n                PRIVATE_MEMORY_SECONDS,\n                PRIVATE_MEMORY_MAX_MESSAGES,\n            )\n\n        # Группа: память разговора за последние пять минут\n        elif (\n''',
        "private user memory before Gemini",
    )

    replace_once(
        "bot.py",
        '''        answer = await ask_gemini(\n''',
        '''            # Как и в личке: пользовательское сообщение входит в\n            # память до сетевого await. Это убирает потерю контекста при\n            # concurrent_updates(8).\n            remember_message(\n                GROUP_MEMORY,\n                group_chat_id,\n                "user",\n                user_text,\n                GROUP_MEMORY_SECONDS,\n                GROUP_MEMORY_MAX_MESSAGES,\n                group_author_name,\n            )\n\n        answer = await ask_gemini(\n''',
        "group user memory before Gemini",
    )

    replace_once(
        "bot.py",
        '''            remember_message(\n                PRIVATE_MEMORY,\n                private_user_id,\n                "user",\n                user_text,\n                PRIVATE_MEMORY_SECONDS,\n                PRIVATE_MEMORY_MAX_MESSAGES,\n            )\n\n            remember_message(\n                PRIVATE_MEMORY,\n                private_user_id,\n                "assistant",\n''',
        '''            remember_message(\n                PRIVATE_MEMORY,\n                private_user_id,\n                "assistant",\n''',
        "remove duplicate private user memory after Gemini",
    )

    replace_once(
        "bot.py",
        '''            remember_message(\n                GROUP_MEMORY,\n                group_chat_id,\n                "user",\n                user_text,\n                GROUP_MEMORY_SECONDS,\n                GROUP_MEMORY_MAX_MESSAGES,\n                group_author_name,\n            )\n\n            remember_message(\n                GROUP_MEMORY,\n                group_chat_id,\n                "assistant",\n''',
        '''            remember_message(\n                GROUP_MEMORY,\n                group_chat_id,\n                "assistant",\n''',
        "remove duplicate group user memory after Gemini",
    )


def patch_module_pruning() -> None:
    # state_engine
    state = Path("state_engine.py")
    text = state.read_text(encoding="utf-8")
    if "def prune_stale_state(" not in text:
        marker = '''\ndef aggression_probability_bonus(state: str) -> float:\n'''
        addition = '''\ndef prune_stale_state(\n    max_age_seconds: float,\n    *,\n    now: float | None = None,\n) -> int:\n    current = time.monotonic() if now is None else now\n    stale = []\n    for chat_id, entry in _CHAT_STATE.items():\n        latest = max(\n            entry.last_seen_at or 0.0,\n            entry.annoyed_marked_at,\n            entry.argumentative_marked_at,\n        )\n        if latest <= 0.0 or current - latest > max_age_seconds:\n            stale.append(chat_id)\n    for chat_id in stale:\n        _CHAT_STATE.pop(chat_id, None)\n    return len(stale)\n\n\n'''
        if marker not in text:
            raise SystemExit("state prune marker missing")
        state.write_text(text.replace(marker, addition + marker, 1), encoding="utf-8")

    # aggression_engine
    agg = Path("aggression_engine.py")
    text = agg.read_text(encoding="utf-8")
    if "def prune_stale_state(" not in text:
        old = '''    def clear(self) -> None:\n        self._last.clear()\n\n\nCOOLDOWN = AggressionCooldown()\n'''
        new = '''    def clear(self) -> None:\n        self._last.clear()\n\n    def prune_stale(\n        self,\n        max_age_seconds: float,\n        *,\n        now: float | None = None,\n    ) -> int:\n        current = time.monotonic() if now is None else now\n        stale = [\n            key\n            for key, last in self._last.items()\n            if current - last > max_age_seconds\n        ]\n        for key in stale:\n            self._last.pop(key, None)\n        return len(stale)\n\n\nCOOLDOWN = AggressionCooldown()\n\n\ndef prune_stale_state(\n    max_age_seconds: float,\n    *,\n    now: float | None = None,\n) -> int:\n    return COOLDOWN.prune_stale(max_age_seconds, now=now)\n'''
        if old not in text:
            raise SystemExit("aggression prune marker missing")
        agg.write_text(text.replace(old, new, 1), encoding="utf-8")

    # passive_engine
    passive = Path("passive_engine.py")
    text = passive.read_text(encoding="utf-8")
    if "_LAST_ACTIVITY_AT" not in text:
        text = text.replace(
            '''_ACTIVITY_SINCE_DROP: dict[int, int] = defaultdict(int)\n_LAST_DROP_AT: dict[int, float] = {}\n''',
            '''_ACTIVITY_SINCE_DROP: dict[int, int] = defaultdict(int)\n_LAST_ACTIVITY_AT: dict[int, float] = {}\n_LAST_DROP_AT: dict[int, float] = {}\n''',
            1,
        )
        text = text.replace(
            '''    _ACTIVITY_SINCE_DROP.clear()\n    _LAST_DROP_AT.clear()\n''',
            '''    _ACTIVITY_SINCE_DROP.clear()\n    _LAST_ACTIVITY_AT.clear()\n    _LAST_DROP_AT.clear()\n''',
            1,
        )
        text = text.replace(
            '''    _ACTIVITY_SINCE_DROP[chat_id] += 1\n    return _ACTIVITY_SINCE_DROP[chat_id]\n''',
            '''    _ACTIVITY_SINCE_DROP[chat_id] += 1\n    _LAST_ACTIVITY_AT[chat_id] = time.monotonic()\n    return _ACTIVITY_SINCE_DROP[chat_id]\n''',
            1,
        )
        marker = '''\ndef build_fatigue_instruction(decision: FatigueDecision) -> str:\n'''
        addition = '''\ndef prune_stale_state(\n    max_age_seconds: float,\n    *,\n    now: float | None = None,\n) -> int:\n    current = time.monotonic() if now is None else now\n    chat_ids = set(_ACTIVITY_SINCE_DROP) | set(_LAST_ACTIVITY_AT) | set(_LAST_DROP_AT) | set(_RECENT_DROPS) | set(_BOT_CALLS) | set(_LAST_FATIGUE_AT) | set(_RECENT_FATIGUE)\n    stale = []\n    for chat_id in chat_ids:\n        calls = _BOT_CALLS.get(chat_id)\n        latest_call = calls[-1] if calls else 0.0\n        latest = max(\n            _LAST_ACTIVITY_AT.get(chat_id, 0.0),\n            _LAST_DROP_AT.get(chat_id, 0.0),\n            _LAST_FATIGUE_AT.get(chat_id, 0.0),\n            latest_call,\n        )\n        if latest <= 0.0 or current - latest > max_age_seconds:\n            stale.append(chat_id)\n    for chat_id in stale:\n        _ACTIVITY_SINCE_DROP.pop(chat_id, None)\n        _LAST_ACTIVITY_AT.pop(chat_id, None)\n        _LAST_DROP_AT.pop(chat_id, None)\n        _RECENT_DROPS.pop(chat_id, None)\n        _BOT_CALLS.pop(chat_id, None)\n        _LAST_FATIGUE_AT.pop(chat_id, None)\n        _RECENT_FATIGUE.pop(chat_id, None)\n    return len(stale)\n\n\n'''
        if marker not in text:
            raise SystemExit("passive prune marker missing")
        passive.write_text(text.replace(marker, addition + marker, 1), encoding="utf-8")

    # style_engine
    style = Path("style_engine.py")
    text = style.read_text(encoding="utf-8")
    if "_LENGTH_LAST_SEEN" not in text:
        text = text.replace("import random\n", "import random\nimport time\n", 1)
        text = text.replace(
            '''_LENGTH_HISTORY: dict[int, deque[str]] = defaultdict(\n    lambda: deque(maxlen=5)\n)\n''',
            '''_LENGTH_HISTORY: dict[int, deque[str]] = defaultdict(\n    lambda: deque(maxlen=5)\n)\n_LENGTH_LAST_SEEN: dict[int, float] = {}\n''',
            1,
        )
        text = text.replace(
            '''    if record:\n        history.append(category)\n''',
            '''    if record:\n        history.append(category)\n        _LENGTH_LAST_SEEN[chat_id] = time.monotonic()\n''',
            1,
        )
        text = text.replace(
            '''def reset_length_history(chat_id: int | None = None) -> None:\n    if chat_id is None:\n        _LENGTH_HISTORY.clear()\n    else:\n        _LENGTH_HISTORY.pop(chat_id, None)\n''',
            '''def reset_length_history(chat_id: int | None = None) -> None:\n    if chat_id is None:\n        _LENGTH_HISTORY.clear()\n        _LENGTH_LAST_SEEN.clear()\n    else:\n        _LENGTH_HISTORY.pop(chat_id, None)\n        _LENGTH_LAST_SEEN.pop(chat_id, None)\n\n\ndef prune_stale_state(\n    max_age_seconds: float,\n    *,\n    now: float | None = None,\n) -> int:\n    current = time.monotonic() if now is None else now\n    stale = [\n        chat_id\n        for chat_id, last_seen in _LENGTH_LAST_SEEN.items()\n        if current - last_seen > max_age_seconds\n    ]\n    for chat_id in stale:\n        _LENGTH_HISTORY.pop(chat_id, None)\n        _LENGTH_LAST_SEEN.pop(chat_id, None)\n    return len(stale)\n''',
            1,
        )
        style.write_text(text, encoding="utf-8")


def patch_bot_cleanup_and_duels() -> None:
    replace_once(
        "bot.py",
        '''PENDING_DUELS: dict[str, dict[str, Any]] = {}\n''',
        '''PENDING_DUELS: dict[str, dict[str, Any]] = {}\nPENDING_DUEL_TTL_SECONDS = 15 * 60\n''',
        "duel ttl constant",
    )
    replace_once(
        "bot.py",
        '''    PENDING_DUELS[token] = {\n        "chat_id": update.effective_chat.id,\n''',
        '''    PENDING_DUELS[token] = {\n        "created_at": time.monotonic(),\n        "chat_id": update.effective_chat.id,\n''',
        "duel created timestamp",
    )
    replace_once(
        "bot.py",
        '''    if duel is None:\n        await query.answer(\n            "Эта дуэль уже неактуальна.",\n            show_alert=True,\n        )\n        return\n''',
        '''    if duel is None:\n        await query.answer(\n            "Эта дуэль уже неактуальна.",\n            show_alert=True,\n        )\n        return\n\n    if (\n        time.monotonic() - float(duel.get("created_at", 0.0))\n        > PENDING_DUEL_TTL_SECONDS\n    ):\n        await query.answer(\n            "Эта дуэль уже протухла. Вызови заново.",\n            show_alert=True,\n        )\n        return\n''',
        "duel callback expiry",
    )

    replace_once(
        "bot.py",
        '''    for key in stale_trigger_user_keys:\n        TRIGGER_REPLY_LAST_BY_USER.pop(key, None)\n\n    return {\n''',
        '''    for key in stale_trigger_user_keys:\n        TRIGGER_REPLY_LAST_BY_USER.pop(key, None)\n\n    stale_last_message_keys = [\n        key\n        for key, (recorded_at, _text) in LAST_USER_TEXT_MESSAGE.items()\n        if now - recorded_at > max_age_seconds\n    ]\n    for key in stale_last_message_keys:\n        LAST_USER_TEXT_MESSAGE.pop(key, None)\n\n    stale_duel_tokens = [\n        token\n        for token, duel in PENDING_DUELS.items()\n        if now - float(duel.get("created_at", 0.0)) > PENDING_DUEL_TTL_SECONDS\n    ]\n    for token in stale_duel_tokens:\n        PENDING_DUELS.pop(token, None)\n\n    stale_state_chats = state_engine.prune_stale_state(\n        max_age_seconds, now=now\n    )\n    stale_passive_chats = passive_engine.prune_stale_state(\n        max_age_seconds, now=now\n    )\n    stale_aggression_keys = aggression_engine.prune_stale_state(\n        max_age_seconds, now=now\n    )\n    stale_length_chats = style_engine.prune_stale_state(\n        max_age_seconds, now=now\n    )\n\n    return {\n''',
        "extend runtime cleanup",
    )

    replace_once(
        "bot.py",
        '''        "trigger_user_keys": len(stale_trigger_user_keys),\n    }\n''',
        '''        "trigger_user_keys": len(stale_trigger_user_keys),\n        "last_user_messages": len(stale_last_message_keys),\n        "pending_duels": len(stale_duel_tokens),\n        "state_chats": stale_state_chats,\n        "passive_chats": stale_passive_chats,\n        "aggression_keys": stale_aggression_keys,\n        "length_chats": stale_length_chats,\n    }\n''',
        "cleanup metrics",
    )


def write_tests() -> None:
    Path("tests/test_v2_runtime_robustness.py").write_text(
        '''import asyncio\nimport sqlite3\nfrom pathlib import Path\n\nimport aggression_engine\nimport bot\nimport passive_engine\nimport state_engine\nimport style_engine\n\n\ndef test_db_context_manager_really_closes_connection(tmp_path):\n    connection = None\n    with bot.get_db_connection(tmp_path / "close.db") as connection:\n        connection.execute("CREATE TABLE t (x INTEGER)")\n    try:\n        connection.execute("SELECT 1")\n    except sqlite3.ProgrammingError:\n        pass\n    else:\n        raise AssertionError("SQLite connection remained open after with-block")\n\n\ndef test_runtime_module_state_can_be_pruned():\n    state_engine.reset_state()\n    state_engine.resolve_state(101, conversation_mode="normal", now=10.0)\n    assert state_engine.prune_stale_state(50.0, now=100.0) == 1\n\n    aggression_engine.COOLDOWN.clear()\n    aggression_engine.COOLDOWN.record(1, 2, now=10.0)\n    assert aggression_engine.prune_stale_state(50.0, now=100.0) == 1\n\n    passive_engine.reset_state()\n    passive_engine.note_group_activity(202)\n    passive_engine._LAST_ACTIVITY_AT[202] = 10.0\n    assert passive_engine.prune_stale_state(50.0, now=100.0) == 1\n\n    style_engine.reset_length_history()\n    style_engine._LENGTH_HISTORY[303].append("short")\n    style_engine._LENGTH_LAST_SEEN[303] = 10.0\n    assert style_engine.prune_stale_state(50.0, now=100.0) == 1\n\n\ndef test_cleanup_removes_stale_last_message_and_duel(monkeypatch):\n    bot.LAST_USER_TEXT_MESSAGE.clear()\n    bot.PENDING_DUELS.clear()\n    bot.LAST_USER_TEXT_MESSAGE[(1, 2)] = (1.0, "old")\n    bot.PENDING_DUELS["dead"] = {"created_at": 1.0}\n    monkeypatch.setattr(bot.time, "monotonic", lambda: 10_000.0)\n    result = bot.cleanup_in_memory_state(max_age_seconds=100.0)\n    assert (1, 2) not in bot.LAST_USER_TEXT_MESSAGE\n    assert "dead" not in bot.PENDING_DUELS\n    assert result["last_user_messages"] >= 1\n    assert result["pending_duels"] >= 1\n\n\ndef test_group_engagement_does_not_leave_zero_key():\n    bot.GROUP_IGNORED_STREAK.clear()\n    bot.GROUP_IGNORED_STREAK[5] = 2\n    bot.register_group_engagement(5)\n    assert 5 not in bot.GROUP_IGNORED_STREAK\n\n\ndef test_hard_mode_cooldowns_are_reserved_before_network_await():\n    source = Path("bot.py").read_text(encoding="utf-8")\n    start = source.index("async def hard_mode_listener(")\n    end = source.index("async def enforce_rate_limit(", start)\n    block = source[start:end]\n    trigger_set = block.index('context.chat_data[\\n            "hard_last_trigger_reply"')\n    trigger_await = block.index("await update.message.reply_text", trigger_set)\n    assert trigger_set < trigger_await\n    reaction_set = block.index('context.chat_data[\\n            "hard_last_reaction"')\n    reaction_await = block.index("await update.message.set_reaction", reaction_set)\n    assert reaction_set < reaction_await\n    random_set = block.index('context.chat_data[\\n                "hard_last_random_reply"')\n    random_await = block.index("await update.message.reply_text(drop_decision.text)", random_set)\n    assert random_set < random_await\n\n\ndef test_text_user_memory_is_recorded_before_gemini_await():\n    source = Path("bot.py").read_text(encoding="utf-8")\n    start = source.index("async def answer_text_message(")\n    end = source.index("async def answer_photo(", start)\n    block = source[start:end]\n    ask_pos = block.index("answer = await ask_gemini(")\n    private_user = block.index('PRIVATE_MEMORY,\\n                private_user_id,\\n                "user"')\n    group_user = block.index('GROUP_MEMORY,\\n                group_chat_id,\\n                "user"')\n    assert private_user < ask_pos\n    assert group_user < ask_pos\n    after_ask = block[ask_pos:]\n    assert 'PRIVATE_MEMORY,\\n                private_user_id,\\n                "user"' not in after_ask\n    assert 'GROUP_MEMORY,\\n                group_chat_id,\\n                "user"' not in after_ask\n''',
        encoding="utf-8",
    )


def main() -> None:
    patch_sqlite_closing()
    patch_hard_mode_reservations()
    patch_memory_order()
    patch_module_pruning()
    patch_bot_cleanup_and_duels()
    write_tests()
    print("Runtime robustness repairs applied.")


if __name__ == "__main__":
    main()
