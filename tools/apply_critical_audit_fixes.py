from __future__ import annotations

import ast
from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0 and new in text:
        return
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_ask_gemini_calls() -> None:
    path = Path("bot.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    edits: list[tuple[int, list[str], str, int]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[ast.AST] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.stack.append(node)
            self.generic_visit(node)
            self.stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.stack.append(node)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node: ast.Call) -> None:
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr

            if name == "ask_gemini" and self.stack:
                fn = self.stack[-1]
                args = getattr(fn, "args", None)
                if args is not None:
                    fn_args = {
                        arg.arg
                        for arg in (
                            list(args.posonlyargs)
                            + list(args.args)
                            + list(args.kwonlyargs)
                        )
                    }
                    if "update" in fn_args:
                        keywords = {kw.arg for kw in node.keywords if kw.arg}
                        missing = [
                            key
                            for key in ("chat_id", "chat_type", "user_id")
                            if key not in keywords
                        ]
                        if missing:
                            close_index = node.end_lineno - 1
                            close_line = lines[close_index]
                            stripped = close_line.lstrip()
                            if not stripped.startswith(")"):
                                raise SystemExit(
                                    f"ask_gemini call in {getattr(fn, 'name', '?')} line {node.lineno} "
                                    "does not close on its own line; refusing unsafe patch"
                                )
                            indent = close_line[: len(close_line) - len(stripped)]
                            inner = indent + "    "
                            additions: list[str] = []
                            if "chat_id" in missing:
                                additions += [
                                    inner + "chat_id=(\n",
                                    inner + "    update.effective_chat.id\n",
                                    inner + "    if update.effective_chat\n",
                                    inner + "    else None\n",
                                    inner + "),\n",
                                ]
                            if "chat_type" in missing:
                                additions += [
                                    inner + "chat_type=(\n",
                                    inner + "    str(update.effective_chat.type)\n",
                                    inner + "    if update.effective_chat\n",
                                    inner + "    else \"private\"\n",
                                    inner + "),\n",
                                ]
                            if "user_id" in missing:
                                additions += [
                                    inner + "user_id=(\n",
                                    inner + "    update.effective_user.id\n",
                                    inner + "    if update.effective_user\n",
                                    inner + "    else None\n",
                                    inner + "),\n",
                                ]
                            edits.append(
                                (close_index, additions, getattr(fn, "name", "?"), node.lineno)
                            )
            self.generic_visit(node)

    Visitor().visit(tree)

    for close_index, additions, _fn, _line in sorted(edits, reverse=True):
        lines[close_index:close_index] = additions

    if edits:
        path.write_text("".join(lines), encoding="utf-8")

    # Permanent static invariant after patch.
    patched = path.read_text(encoding="utf-8")
    patched_tree = ast.parse(patched)
    missing_after: list[tuple[str, int, list[str]]] = []

    class CheckVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[ast.AST] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.stack.append(node)
            self.generic_visit(node)
            self.stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.stack.append(node)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node: ast.Call) -> None:
            name = node.func.id if isinstance(node.func, ast.Name) else None
            if name == "ask_gemini" and self.stack:
                fn = self.stack[-1]
                args = getattr(fn, "args", None)
                fn_args = {
                    arg.arg
                    for arg in (
                        list(args.posonlyargs)
                        + list(args.args)
                        + list(args.kwonlyargs)
                    )
                }
                if "update" in fn_args:
                    kws = {kw.arg for kw in node.keywords if kw.arg}
                    missing = [
                        key
                        for key in ("chat_id", "chat_type", "user_id")
                        if key not in kws
                    ]
                    if missing:
                        missing_after.append((getattr(fn, "name", "?"), node.lineno, missing))
            self.generic_visit(node)

    CheckVisitor().visit(patched_tree)
    if missing_after:
        raise SystemExit(f"ask_gemini context still missing: {missing_after}")

    print(f"ask_gemini update-based calls patched: {len(edits)}")


def patch_bot_state_and_titles() -> None:
    replace_once(
        "bot.py",
        '''        character_state = state_engine.resolve_state(\n            chat_id if chat_id is not None else 0,\n            conversation_mode=conversation_mode,\n        )\n''',
        '''        if chat_id is None:\n            if conversation_mode == "serious":\n                character_state = state_engine.STATE_SERIOUS\n            elif conversation_mode == "hostile":\n                character_state = state_engine.STATE_HOSTILE_RESPONSE\n            else:\n                character_state = state_engine.STATE_NORMAL\n        else:\n            character_state = state_engine.resolve_state(\n                chat_id,\n                conversation_mode=conversation_mode,\n            )\n''',
        "stateless state fallback",
    )

    replace_once(
        "bot.py",
        '''        aggression_decision = aggression_engine.decide_aggression(\n            aggression_engine.AggressionContext(\n                user_text=style_text,\n                intent=resolved_intent,\n                confidence=intent_confidence,\n                chat_type=chat_type,\n                roughness=str(settings.get("roughness", "medium")),\n                relationship_level=social_ctx.relationship_level,\n                serious_topic=(conversation_mode == "serious"),\n                emotional_tone=emotional_tone,\n                recent_messages=tuple(recent_messages or ()),\n                chat_id=tracker_chat_id,\n                user_id=user_id or 0,\n                character_state=character_state,\n            )\n        )\n        aggression_instruction = aggression_engine.build_aggression_instruction(\n            aggression_decision\n        )\n        if aggression_instruction:\n            current_instruction += aggression_instruction\n            state_engine.mark_argumentative(tracker_chat_id)\n''',
        '''        if chat_id is not None and user_id is not None:\n            aggression_decision = aggression_engine.decide_aggression(\n                aggression_engine.AggressionContext(\n                    user_text=style_text,\n                    intent=resolved_intent,\n                    confidence=intent_confidence,\n                    chat_type=chat_type,\n                    roughness=str(settings.get("roughness", "medium")),\n                    relationship_level=social_ctx.relationship_level,\n                    serious_topic=(conversation_mode == "serious"),\n                    emotional_tone=emotional_tone,\n                    recent_messages=tuple(recent_messages or ()),\n                    chat_id=chat_id,\n                    user_id=user_id,\n                    character_state=character_state,\n                )\n            )\n            aggression_instruction = aggression_engine.build_aggression_instruction(\n                aggression_decision\n            )\n            if aggression_instruction:\n                current_instruction += aggression_instruction\n                state_engine.mark_argumentative(chat_id)\n''',
        "no shared aggression key zero",
    )

    replace_once(
        "bot.py",
        '''        connection.execute(\n            """\n            UPDATE chat_member_profiles\n            SET current_title = ?, updated_at = datetime('now')\n            WHERE chat_id = ? AND user_id = ?\n            """,\n            (title, chat_id, user_id),\n        )\n        connection.commit()\n        return True\n''',
        '''        update_cursor = connection.execute(\n            """\n            UPDATE chat_member_profiles\n            SET current_title = ?, updated_at = datetime('now')\n            WHERE chat_id = ? AND user_id = ?\n            """,\n            (title, chat_id, user_id),\n        )\n        if update_cursor.rowcount != 1:\n            connection.rollback()\n            return False\n        connection.commit()\n        return True\n''',
        "atomic daily title profile save",
    )

    replace_once(
        "bot.py",
        "import style_engine\nimport voice_runtime\n",
        "import style_engine\nimport title_pools\nimport voice_runtime\n",
        "title_pools import",
    )

    replace_once(
        "bot.py",
        '''def pick_new_title(\n    previous_title: str | None,\n) -> str:\n    """Выбирает новый титул, исключая предыдущий, если это возможно."""\n\n    candidates = [\n        title\n        for title in JOKE_TITLES\n        if title != previous_title\n    ]\n\n    if not candidates:\n        candidates = list(JOKE_TITLES)\n\n    return random.choice(candidates)\n''',
        '''def pick_new_title(\n    previous_title: str | None,\n) -> str:\n    """V2: сначала выбирает личность, затем один из её десяти титулов."""\n\n    return title_pools.pick_title(previous_title)\n''',
        "wire two-stage V2 title picker",
    )


def patch_regexes() -> None:
    replace_once(
        "reaction_engine.py",
        '''    r"судьб\\w*|карм\\w*|зв[её]зд\\w*\\s+(?:говор|шепч|сошл)|"\n''',
        '''    r"судьб\\w*|карм\\w*|зв[её]зд\\w*\\s+(?:говор\\w*|шепч\\w*|сошл\\w*)|"\n''',
        "mysticism inflections",
    )
    replace_once(
        "reaction_engine.py",
        '''    r"\\b(?:аргумент\\w*\\s+(?:умер|сдох|развал)|"\n''',
        '''    r"\\b(?:аргумент\\w*\\s+(?:умер\\w*|сдох\\w*|развал\\w*)|"\n''',
        "dead argument inflections",
    )
    replace_once(
        "reaction_engine.py",
        '''    r"\\b(?:подстав\\w*|крыса\\b|срач\\w*|интриг\\w*|"\n    r"стучит\\b|настучал\\w*|слил\\w*\\s+(?:переписк|инф))\\b",\n''',
        '''    r"\\b(?:подстав\\w*|крыс\\w*|срач\\w*|интриг\\w*|"\n    r"стуч\\w*|настуч\\w*|слил\\w*\\s+(?:переписк\\w*|инф\\w*))\\b",\n''',
        "drama inflections",
    )
    replace_once(
        "intent.py",
        '''    r"\\b(?:это\\s+не\\s+так|чушь|бред полный)\\b",\n''',
        '''    r"\\b(?:это\\s+не\\s+так|чуш\\w*|бред\\w*\\s+полн\\w*|полн\\w*\\s+бред\\w*)\\b",\n''',
        "full nonsense variants",
    )


def patch_state_recency() -> None:
    replace_once(
        "state_engine.py",
        '''    annoyed_until: float = 0.0\n    argumentative_until: float = 0.0\n''',
        '''    annoyed_until: float = 0.0\n    argumentative_until: float = 0.0\n    annoyed_marked_at: float = 0.0\n    argumentative_marked_at: float = 0.0\n''',
        "state timestamps",
    )
    replace_once(
        "state_engine.py",
        '''    entry.annoyed_until = max(\n        entry.annoyed_until,\n        current + ANNOYED_DURATION_SECONDS,\n    )\n''',
        '''    entry.annoyed_until = max(\n        entry.annoyed_until,\n        current + ANNOYED_DURATION_SECONDS,\n    )\n    entry.annoyed_marked_at = current\n''',
        "annoyed marked time",
    )
    replace_once(
        "state_engine.py",
        '''    entry.argumentative_until = max(\n        entry.argumentative_until,\n        current + ARGUMENTATIVE_DURATION_SECONDS,\n    )\n''',
        '''    entry.argumentative_until = max(\n        entry.argumentative_until,\n        current + ARGUMENTATIVE_DURATION_SECONDS,\n    )\n    entry.argumentative_marked_at = current\n''',
        "argumentative marked time",
    )
    replace_once(
        "state_engine.py",
        '''    if conversation_mode == "serious":\n        state = STATE_SERIOUS\n    elif conversation_mode == "hostile":\n        state = STATE_HOSTILE_RESPONSE\n    elif current < entry.annoyed_until:\n        state = STATE_ANNOYED\n    elif current < entry.argumentative_until:\n        state = STATE_ARGUMENTATIVE\n''',
        '''    annoyed_active = current < entry.annoyed_until\n    argumentative_active = current < entry.argumentative_until\n\n    if conversation_mode == "serious":\n        state = STATE_SERIOUS\n    elif conversation_mode == "hostile":\n        state = STATE_HOSTILE_RESPONSE\n    elif annoyed_active and argumentative_active:\n        state = (\n            STATE_ARGUMENTATIVE\n            if entry.argumentative_marked_at >= entry.annoyed_marked_at\n            else STATE_ANNOYED\n        )\n    elif annoyed_active:\n        state = STATE_ANNOYED\n    elif argumentative_active:\n        state = STATE_ARGUMENTATIVE\n''',
        "latest temporary state wins",
    )


def patch_passive_replies() -> None:
    path = Path("passive_engine.py")
    text = path.read_text(encoding="utf-8")
    if "SHORT_ACK_RE" not in text:
        text = text.replace(
            "import random\nimport time\n",
            "import random\nimport re\nimport time\n",
            1,
        )
        insertion = '''\n\nSHORT_ACK_RE = re.compile(\n    r"^\\s*(?:100\\s*%|да|нет|ага|угу|точно|верно|согласен|согласна|"\n    r"ок|окей|ладно|понял|поняла|ясно|\\+1|[👍👎👌🤝🔥😂🤣🙂]+)[.!?,\\s]*$",\n    re.IGNORECASE,\n)\n\nCONTEXTUAL_TEXT_REASONS = frozenset(\n    {\n        "provocation",\n        "contradiction",\n        "absurdity",\n        "dead_argument",\n        "suspicious_drama",\n        "mysticism",\n        "direct_insult",\n        "insult",\n        "joke",\n        "sarcasm",\n        "cringe",\n    }\n)\n\n\ndef random_text_intervention_allowed(\n    text: str,\n    reaction_reason: str | None,\n) -> bool:\n    """Не позволяет hard-mode отвечать случайным текстом без смыслового повода."""\n\n    stripped = text.strip()\n    if not stripped or SHORT_ACK_RE.fullmatch(stripped):\n        return False\n    return bool(reaction_reason and reaction_reason in CONTEXTUAL_TEXT_REASONS)\n'''
        marker = "\n\n@dataclass(frozen=True)\nclass PassiveDropDecision:"
        if marker not in text:
            raise SystemExit("passive helper insertion marker missing")
        text = text.replace(marker, insertion + marker, 1)
        path.write_text(text, encoding="utf-8")

    replace_once(
        "bot.py",
        '''    if (\n        not reacted_to_this_message\n        and now - last_random_reply >= HARD_RANDOM_REPLY_COOLDOWN\n        and random.random() < random_reply_chance\n        and group_random_reply_allowed(chat_id, now)\n    ):\n''',
        '''    if (\n        not reacted_to_this_message\n        and passive_engine.random_text_intervention_allowed(\n            text, reaction_reason\n        )\n        and now - last_random_reply >= HARD_RANDOM_REPLY_COOLDOWN\n        and random.random() < random_reply_chance\n        and group_random_reply_allowed(chat_id, now)\n    ):\n''',
        "context gate for passive text",
    )

    replace_once(
        "bot.py",
        '''        random_reply_text = (\n            drop_decision.text\n            if drop_decision.active and drop_decision.text\n            else random.choice(HARD_RANDOM_REPLIES)\n        )\n        await update.message.reply_text(random_reply_text)\n\n        context.chat_data[\n            "hard_last_random_reply"\n        ] = now\n        record_group_random_reply(chat_id, now)\n\n        await increment_chat_hard_stat(\n            chat_id,\n            "random_replies_count",\n            chat_type,\n        )\n''',
        '''        if drop_decision.active and drop_decision.text:\n            await update.message.reply_text(drop_decision.text)\n\n            context.chat_data[\n                "hard_last_random_reply"\n            ] = now\n            record_group_random_reply(chat_id, now)\n\n            await increment_chat_hard_stat(\n                chat_id,\n                "random_replies_count",\n                chat_type,\n            )\n''',
        "remove uncontextual HARD_RANDOM_REPLIES fallback",
    )


def write_tests() -> None:
    Path("tests/test_v2_audit_critical.py").write_text(
        '''import ast\nfrom pathlib import Path\n\nimport bot\nimport intent\nimport passive_engine\nimport reaction_engine\nimport state_engine\nimport title_pools\n\n\ndef _update_based_missing_ask_context():\n    source = Path("bot.py").read_text(encoding="utf-8")\n    tree = ast.parse(source)\n    missing = []\n\n    class Visitor(ast.NodeVisitor):\n        def __init__(self):\n            self.stack = []\n        def visit_AsyncFunctionDef(self, node):\n            self.stack.append(node)\n            self.generic_visit(node)\n            self.stack.pop()\n        def visit_FunctionDef(self, node):\n            self.stack.append(node)\n            self.generic_visit(node)\n            self.stack.pop()\n        def visit_Call(self, node):\n            if isinstance(node.func, ast.Name) and node.func.id == "ask_gemini" and self.stack:\n                fn = self.stack[-1]\n                fn_args = {a.arg for a in list(fn.args.args) + list(fn.args.kwonlyargs)}\n                if "update" in fn_args:\n                    kws = {kw.arg for kw in node.keywords if kw.arg}\n                    absent = {"chat_id", "chat_type", "user_id"} - kws\n                    if absent:\n                        missing.append((fn.name, node.lineno, absent))\n            self.generic_visit(node)\n    Visitor().visit(tree)\n    return missing\n\n\ndef test_every_update_based_ask_gemini_call_has_identity_context():\n    assert _update_based_missing_ask_context() == []\n\n\ndef test_missing_chat_does_not_touch_shared_state_key_zero(monkeypatch):\n    state_engine.reset_state()\n    bot.build_full_system_instruction("обычный вопрос", chat_id=None, user_id=None)\n    assert 0 not in state_engine._CHAT_STATE\n\n\ndef test_daily_title_rolls_back_if_member_profile_missing(tmp_path, monkeypatch):\n    monkeypatch.setattr(bot, "STATS_DB_PATH", tmp_path / "audit-title.db")\n    bot.initialize_stats_database()\n    with bot.get_db_connection() as connection:\n        connection.execute("INSERT INTO chats (chat_id, chat_type) VALUES (?, 'group')", (-9001,))\n        connection.execute("INSERT INTO users (user_id) VALUES (?)", (991,))\n        connection.commit()\n    assert not bot.try_assign_daily_title_sync(-9001, "2026-08-15", 991, "Товарищ майор")\n    assert bot.get_daily_title_assignment_sync(-9001, "2026-08-15") is None\n\n\ndef test_v2_title_picker_is_real_two_stage_picker(monkeypatch):\n    monkeypatch.setattr(title_pools, "pick_title", lambda previous_title=None: "Товарищ майор")\n    assert bot.pick_new_title("Скуф") == "Товарищ майор"\n\n\ndef test_mysticism_regex_matches_natural_inflection():\n    assert reaction_engine.detect_context_reason("звезды говорят, что мне повезет") == "mysticism"\n\n\ndef test_dead_argument_regex_matches_natural_inflection():\n    assert reaction_engine.detect_context_reason("аргумент развалился на глазах") == "dead_argument"\n\n\ndef test_drama_regex_matches_inflections():\n    assert reaction_engine.detect_context_reason("он опять стучал и слил переписку") == "suspicious_drama"\n    assert reaction_engine.detect_context_reason("какая-то крыса слила инфу") == "suspicious_drama"\n\n\ndef test_full_nonsense_disagreement_variants():\n    assert intent.classify_intent("это полный бред")[0] == "disagreement"\n    assert intent.classify_intent("бред полный вообще")[0] == "disagreement"\n\n\ndef test_latest_temporary_state_wins():\n    state_engine.reset_state()\n    state_engine.mark_annoyed(1, now=1000.0)\n    state_engine.mark_argumentative(1, now=1001.0)\n    assert state_engine.resolve_state(1, conversation_mode="normal", now=1002.0, record=False) == "argumentative"\n    state_engine.reset_state()\n    state_engine.mark_argumentative(2, now=1000.0)\n    state_engine.mark_annoyed(2, now=1001.0)\n    assert state_engine.resolve_state(2, conversation_mode="normal", now=1002.0, record=False) == "annoyed"\n\n\ndef test_short_acknowledgements_never_allow_random_text():\n    for text in ("100%", "да", "нет", "точно", "согласен", "ок", "+1", "👍"):\n        assert not passive_engine.random_text_intervention_allowed(text, "provocation")\n\n\ndef test_good_question_does_not_justify_random_hard_reply():\n    assert not passive_engine.random_text_intervention_allowed(\n        "Яблоко сняли с выборов, удивлен? нет", "good_question"\n    )\n\n\ndef test_contextual_provocation_can_still_open_passive_slot():\n    assert passive_engine.random_text_intervention_allowed(\n        "ну давай, докажи если сможешь", "provocation"\n    )\n\n\ndef test_legacy_random_reply_fallback_removed_from_hard_listener():\n    source = Path("bot.py").read_text(encoding="utf-8")\n    start = source.index("async def hard_mode_listener(")\n    end = source.index("async def enforce_rate_limit(", start)\n    hard_listener = source[start:end]\n    assert "random.choice(HARD_RANDOM_REPLIES)" not in hard_listener\n''',
        encoding="utf-8",
    )


def main() -> None:
    patch_ask_gemini_calls()
    patch_bot_state_and_titles()
    patch_regexes()
    patch_state_recency()
    patch_passive_replies()
    write_tests()
    print("Critical audit repairs applied.")


if __name__ == "__main__":
    main()
