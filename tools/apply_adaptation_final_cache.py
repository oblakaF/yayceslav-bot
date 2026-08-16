from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"marker not found: {label}")
    return text.replace(old, new, 1)


path = Path("bot.py")
text = path.read_text(encoding="utf-8")

text = replace_once(
    text,
    "import aggression_engine\nimport chat_native_engine\n",
    "import aggression_engine\nimport adaptation_cache\nimport chat_native_engine\n",
    "adaptation cache import",
)

old_reads = '''        adaptation = (
            get_chat_feedback_adaptation_sync(chat_id)
            if chat_id is not None and chat_type in ("group", "supergroup")
            else feedback_engine.build_adaptation(())
        )
        native_profile = (
            get_chat_native_profile_sync(chat_id)
            if chat_id is not None and chat_type in ("group", "supergroup")
            else {"terms": []}
        )
'''

new_reads = '''        if chat_id is not None and chat_type in ("group", "supergroup"):
            adaptation = adaptation_cache.get_or_load(
                "feedback",
                chat_id,
                lambda: get_chat_feedback_adaptation_sync(chat_id),
                ttl_seconds=45.0,
            )
            native_profile = adaptation_cache.get_or_load(
                "native",
                chat_id,
                lambda: get_chat_native_profile_sync(chat_id),
                ttl_seconds=300.0,
            )
        else:
            adaptation = feedback_engine.build_adaptation(())
            native_profile = {"terms": []}
'''
text = replace_once(text, old_reads, new_reads, "cached instruction reads")

text = replace_once(
    text,
    '''    now = datetime.now(timezone.utc)
    refreshed = 0
    with get_db_connection() as connection:
''',
    '''    now = datetime.now(timezone.utc)
    refreshed = 0
    refreshed_chat_ids: set[int] = set()
    with get_db_connection() as connection:
''',
    "native refresh id set",
)

text = replace_once(
    text,
    '''            refreshed += 1

        # Не даём словарю расти бесконечно:''',
    '''            refreshed += 1
            refreshed_chat_ids.add(chat_id)

        # Не даём словарю расти бесконечно:''',
    "native refresh track ids",
)

text = replace_once(
    text,
    '''        connection.commit()
    return refreshed


async def refresh_due_chat_native_profiles() -> int:
''',
    '''        connection.commit()

    for refreshed_chat_id in refreshed_chat_ids:
        adaptation_cache.invalidate("native", refreshed_chat_id)

    return refreshed


async def refresh_due_chat_native_profiles() -> int:
''',
    "native cache invalidation",
)

old_reaction = '''    await asyncio.to_thread(
        apply_bot_reaction_delta_sync,
        reaction.chat.id,
        reaction.message_id,
        score_delta,
        count_delta,
    )
'''
new_reaction = '''    updated = await asyncio.to_thread(
        apply_bot_reaction_delta_sync,
        reaction.chat.id,
        reaction.message_id,
        score_delta,
        count_delta,
    )
    if updated:
        adaptation_cache.invalidate("feedback", reaction.chat.id)
'''
text = replace_once(text, old_reaction, new_reaction, "feedback cache invalidation")

path.write_text(text, encoding="utf-8")
print("final adaptation cache patch applied")
