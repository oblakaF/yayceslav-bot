from pathlib import Path

path = Path("tools/apply_runtime_robustness_fixes.py")
text = path.read_text(encoding="utf-8")

old = '''    replace_once(\n        "bot.py",\n        ''' + "'''        answer = await ask_gemini(\\n'''" + ''',\n        ''' + "'''            # Как и в личке: пользовательское сообщение входит в\\n            # память до сетевого await. Это убирает потерю контекста при\\n            # concurrent_updates(8).\\n            remember_message(\\n                GROUP_MEMORY,\\n                group_chat_id,\\n                \"user\",\\n                user_text,\\n                GROUP_MEMORY_SECONDS,\\n                GROUP_MEMORY_MAX_MESSAGES,\\n                group_author_name,\\n            )\\n\\n        answer = await ask_gemini(\\n'''" + ''',\n        "group user memory before Gemini",\n    )\n'''

new = '''    # Этот якорь встречается во многих командах, поэтому патчим только\n    # тело answer_text_message(), а не весь bot.py.\n    bot_path = Path("bot.py")\n    bot_text = bot_path.read_text(encoding="utf-8")\n    fn_start = bot_text.index("async def answer_text_message(")\n    fn_end = bot_text.index("async def answer_photo(", fn_start)\n    fn_block = bot_text[fn_start:fn_end]\n    group_ask_anchor = "        answer = await ask_gemini(\\n"\n    group_insert = ''' + "'''            # Как и в личке: пользовательское сообщение входит в\n            # память до сетевого await. Это убирает потерю контекста при\n            # concurrent_updates(8).\n            remember_message(\n                GROUP_MEMORY,\n                group_chat_id,\n                \"user\",\n                user_text,\n                GROUP_MEMORY_SECONDS,\n                GROUP_MEMORY_MAX_MESSAGES,\n                group_author_name,\n            )\n\n        answer = await ask_gemini(\n'''" + '''\n    if fn_block.count(group_ask_anchor) != 1:\n        raise SystemExit(\n            f"group user memory before Gemini: expected 1 match inside "\n            f"answer_text_message, got {fn_block.count(group_ask_anchor)}"\n        )\n    fn_block = fn_block.replace(group_ask_anchor, group_insert, 1)\n    bot_path.write_text(\n        bot_text[:fn_start] + fn_block + bot_text[fn_end:],\n        encoding="utf-8",\n    )\n'''

if old in text:
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
elif "expected 1 match inside" not in text:
    raise SystemExit("runtime patcher scope anchor not found")
