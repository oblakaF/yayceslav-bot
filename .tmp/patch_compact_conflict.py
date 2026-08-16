from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"marker not found in {path}: {old[:120]!r}")
    if text.count(old) != 1:
        raise SystemExit(f"marker not unique in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1) Old Russian remains a spice, not the default flavor.
replacements = {
    "        VOICE_PACK_OLD_RUSSIAN: 0.07,\n": "        VOICE_PACK_OLD_RUSSIAN: 0.045,\n",
    "        VOICE_PACK_OLD_RUSSIAN: 0.09,\n": "        VOICE_PACK_OLD_RUSSIAN: 0.055,\n",
    "        VOICE_PACK_OLD_RUSSIAN: 0.06,\n": "        VOICE_PACK_OLD_RUSSIAN: 0.040,\n",
    "        VOICE_PACK_OLD_RUSSIAN: 0.05,\n": "        VOICE_PACK_OLD_RUSSIAN: 0.030,\n",
}
for old, new in replacements.items():
    replace_once("style_engine.py", old, new)

# Challenge should also be terse: many live insults land here rather than hostile.
replace_once(
    "style_engine.py",
    '''    if ctx.conversation_mode == "challenge":\n        return {\n            "micro": 0.55,\n            "short": 0.38,\n            "normal": 0.07,\n            "long": 0.00,\n        }\n''',
    '''    if ctx.conversation_mode == "challenge":\n        return {\n            "micro": 0.78,\n            "short": 0.22,\n            "normal": 0.00,\n            "long": 0.00,\n        }\n''',
)

# 2) Expose current hostile streak so the send layer can enforce the same rhythm.
insert_after = '''def is_escalated(count: int) -> bool:\n    return HOSTILE_ESCALATION_FROM <= int(count) <= HOSTILE_STREAK_MAX\n\n\n'''
replace_once(
    "hostile_streak_engine.py",
    insert_after,
    insert_after + '''def current(chat_id: int, user_id: int, *, now: float | None = None) -> int:\n    current_time = time.monotonic() if now is None else float(now)\n    entry = _STREAKS.get((int(chat_id), int(user_id)))\n    if entry is None:\n        return 0\n    if current_time - entry.last_at > HOSTILE_STREAK_WINDOW_SECONDS:\n        return 0\n    return entry.count\n\n\n''',
)

# 3) Humanizer gets a deterministic compact conflict layer before random effects.
replace_once(
    "humanizer_engine.py",
    "SPLIT_CHANCE = 0.08\n",
    "SPLIT_CHANCE = 0.08\nCONFLICT_TWO_MESSAGE_CHANCE = 0.38\n",
)
replace_once(
    "humanizer_engine.py",
    '''def _split_naturally(text: str) -> tuple[str, str] | None:\n''',
    '''def _compact_conflict_text(\n    text: str,\n    *,\n    max_chars: int,\n    max_sentences: int = 2,\n) -> tuple[str, ...]:\n    clean = " ".join((text or "").split())\n    if not clean:\n        return ("",)\n\n    sentences = [part.strip() for part in _SENTENCE_BOUNDARY_RE.split(clean) if part.strip()]\n    if not sentences:\n        sentences = [clean]\n\n    kept: list[str] = []\n    total = 0\n    for sentence in sentences[:max_sentences]:\n        projected = total + (1 if kept else 0) + len(sentence)\n        if projected <= max_chars:\n            kept.append(sentence)\n            total = projected\n            continue\n        if not kept:\n            clipped = sentence[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:-")\n            kept.append((clipped or sentence[:max_chars]).rstrip() + "…")\n        break\n\n    return tuple(kept or [clean[:max_chars]])\n\n\ndef _split_naturally(text: str) -> tuple[str, str] | None:\n''',
)
replace_once(
    "humanizer_engine.py",
    '''def humanize_reply(\n    text: str,\n    *,\n    user_text: str = "",\n    trace=None,\n    rng=random,\n) -> HumanizedReply:\n''',
    '''def humanize_reply(\n    text: str,\n    *,\n    user_text: str = "",\n    trace=None,\n    hostile_streak: int = 0,\n    rng=random,\n) -> HumanizedReply:\n''',
)
replace_once(
    "humanizer_engine.py",
    '''    important = _important_request(user_text, trace)\n\n    if not important:\n''',
    '''    important = _important_request(user_text, trace)\n    mode = getattr(trace, "conversation_mode", "normal") if trace else "normal"\n\n    # Conflict rhythm is enforced after Gemini, not merely requested in the prompt.\n    # First/second hostile turn and ordinary challenge: one or two compact phrases.\n    # Third/fourth hostile turn remains the intentional longer flare-up.\n    compact_conflict = (\n        mode == "challenge"\n        or (mode == "hostile" and int(hostile_streak) < 3)\n    )\n    if compact_conflict and not important:\n        max_chars = 125 if mode == "hostile" else 155\n        pieces = _compact_conflict_text(clean, max_chars=max_chars, max_sentences=2)\n        compact = " ".join(pieces).strip()\n        if len(pieces) >= 2 and rng.random() < CONFLICT_TWO_MESSAGE_CHANCE:\n            return HumanizedReply(\n                (pieces[0], pieces[1]),\n                (0.0, rng.uniform(0.65, 1.55)),\n                "conflict_split",\n            )\n        return HumanizedReply((compact,), (0.0,), "conflict_compact")\n\n    if not important:\n''',
)

# 4) Wire the already-observed streak into send_answer without changing Gemini logic.
replace_once(
    "bot.py",
    '''    trace = feedback_engine.get_current_trace()\n    if source_user_text is None:\n''',
    '''    trace = feedback_engine.get_current_trace()\n    current_hostile_streak = 0\n    if (\n        trace is not None\n        and getattr(trace, "conversation_mode", "") == "hostile"\n        and update.effective_chat\n        and update.effective_user\n        and update.effective_chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)\n    ):\n        current_hostile_streak = hostile_streak_engine.current(\n            update.effective_chat.id,\n            update.effective_user.id,\n        )\n\n    if source_user_text is None:\n''',
)
replace_once(
    "bot.py",
    '''        plan = humanizer_engine.humanize_reply(\n            answer_text,\n            user_text=source_user_text,\n            trace=trace,\n        )\n''',
    '''        plan = humanizer_engine.humanize_reply(\n            answer_text,\n            user_text=source_user_text,\n            trace=trace,\n            hostile_streak=current_hostile_streak,\n        )\n''',
)

# 5) Permanent regression tests.
Path("tests/test_compact_conflict_humanizer.py").write_text(
    '''import random\n\nimport feedback_engine\nimport humanizer_engine\nimport hostile_streak_engine\nimport style_engine\n\n\ndef _trace(mode):\n    return feedback_engine.ResponseTrace(\n        chat_id=1, chat_type="group", conversation_mode=mode, message_intent="small_talk"\n    )\n\n\ndef test_first_hostile_turn_is_physically_compacted_after_generation():\n    text = (\n        "Слышь, лопух, ты зеркало с чатом перепутал? "\n        "Ты с батей-то посдержаннее общайся. "\n        "А теперь начинается длинная ненужная лекция про аргументацию и контекст."\n    )\n    plan = humanizer_engine.humanize_reply(\n        text, user_text="еблан", trace=_trace("hostile"), hostile_streak=1, rng=random.Random(9)\n    )\n    joined = " ".join(plan.messages)\n    assert "лекция" not in joined\n    assert len(joined) <= 125\n    assert len(plan.messages) in {1, 2}\n\n\ndef test_short_direct_sendoff_stays_short():\n    plan = humanizer_engine.humanize_reply(\n        "Иди нахуй. Сейчас я тебе ещё объясню почему ты неправ.",\n        user_text="пошел нахуй", trace=_trace("hostile"), hostile_streak=1, rng=random.Random(4)\n    )\n    assert "объясню" not in " ".join(plan.messages)\n    assert len(" ".join(plan.messages)) <= 125\n\n\ndef test_third_hostile_turn_is_not_forced_through_compact_layer():\n    text = "Первое предложение. Второе предложение. Третье предложение — это уже сознательный разнос."\n    plan = humanizer_engine.humanize_reply(\n        text, user_text="пошел нахуй", trace=_trace("hostile"), hostile_streak=3, rng=random.Random(2)\n    )\n    assert "Третье предложение" in " ".join(plan.messages)\n\n\ndef test_challenge_is_also_compact_even_if_classifier_does_not_call_it_hostile():\n    text = "О, уровень аргументации вырос до небес. Ты прямо гений контекста. А теперь длинный второй абзац."\n    plan = humanizer_engine.humanize_reply(\n        text, user_text="а ты гений простыней", trace=_trace("challenge"), rng=random.Random(3)\n    )\n    assert len(" ".join(plan.messages)) <= 155\n    assert "длинный второй абзац" not in " ".join(plan.messages)\n\n\ndef test_old_russian_weight_is_reduced_but_forced_rus_remains_forced():\n    assert style_engine._VOICE_PACK_WEIGHTS_BY_MODE["normal"][style_engine.VOICE_PACK_OLD_RUSSIAN] == 0.045\n    assert style_engine._VOICE_PACK_WEIGHTS_BY_MODE["hostile"][style_engine.VOICE_PACK_OLD_RUSSIAN] == 0.030\n    assert style_engine.choose_voice_pack(\n        style_engine.VoicePackContext(selected_character="rus"), rng=random.Random(1)\n    ) == style_engine.VOICE_PACK_OLD_RUSSIAN\n\n\ndef test_hostile_streak_current_observes_window():\n    hostile_streak_engine.reset()\n    assert hostile_streak_engine.observe(5, 6, hostile=True, now=100.0) == 1\n    assert hostile_streak_engine.current(5, 6, now=101.0) == 1\n    assert hostile_streak_engine.current(5, 6, now=1000.0) == 0\n''',
    encoding="utf-8",
)
