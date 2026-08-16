from pathlib import Path


path = Path("tools/apply_chat_adaptation.py")
text = path.read_text(encoding="utf-8")

bad_block = '''text = replace_once(
    text,
    '    primary: str | None = None\\n',
    '    adaptation = adaptation or {}\\n'
    '    taunt_chance = max(0.12, min(0.28, CONFLICT_TAUNT_CHANCE * float(adaptation.get("taunt_multiplier", 1.0))))\\n'
    '    layered_chance = max(0.15, min(0.35, LAYERED_JOKE_CHANCE_WITHIN_TAUNT * float(adaptation.get("layered_multiplier", 1.0))))\\n'
    '    verdict_multiplier = max(0.85, min(1.15, float(adaptation.get("verdict_multiplier", 1.0))))\\n\\n'
    '    primary: str | None = None\\n',
    "voice adaptation vars",
)
'''

good_block = '''text = replace_once(
    text,
    '    if serious_topic or conversation_mode == "serious" or pack.name == "classic":\\n'
    '        return VoiceMaterial(pack_name=pack.name)\\n\\n'
    '    primary: str | None = None\\n',
    '    if serious_topic or conversation_mode == "serious" or pack.name == "classic":\\n'
    '        return VoiceMaterial(pack_name=pack.name)\\n\\n'
    '    adaptation = adaptation or {}\\n'
    '    taunt_chance = max(0.12, min(0.28, CONFLICT_TAUNT_CHANCE * float(adaptation.get("taunt_multiplier", 1.0))))\\n'
    '    layered_chance = max(0.15, min(0.35, LAYERED_JOKE_CHANCE_WITHIN_TAUNT * float(adaptation.get("layered_multiplier", 1.0))))\\n'
    '    verdict_multiplier = max(0.85, min(1.15, float(adaptation.get("verdict_multiplier", 1.0))))\\n\\n'
    '    primary: str | None = None\\n',
    "voice adaptation vars",
)
'''

if bad_block not in text:
    raise RuntimeError("old broad voice-runtime insertion block not found")
text = text.replace(bad_block, good_block, 1)

old_cleanup = '''        # Не даём словарю расти бесконечно: старые одноразовые кандидаты
        # исчезают, устойчивые мемы/словечки остаются.
        connection.execute(
            """
            DELETE FROM chat_native_term_users
            WHERE NOT EXISTS (
                SELECT 1 FROM chat_native_terms t
                WHERE t.chat_id = chat_native_term_users.chat_id
                  AND t.term = chat_native_term_users.term
            )
            """
        )
'''

new_cleanup = '''        # Не даём словарю расти бесконечно: редкие кандидаты, которые
        # не появлялись 60 дней, забываются. Устойчивые локальные мемы
        # (5+ употреблений) сохраняются и могут вернуться в следующий pack.
        connection.execute(
            """
            DELETE FROM chat_native_terms
            WHERE last_seen < datetime('now', '-60 days')
              AND occurrences < 5
            """
        )
        connection.execute(
            """
            DELETE FROM chat_native_term_users
            WHERE NOT EXISTS (
                SELECT 1 FROM chat_native_terms t
                WHERE t.chat_id = chat_native_term_users.chat_id
                  AND t.term = chat_native_term_users.term
            )
            """
        )
'''

if old_cleanup not in text:
    raise RuntimeError("old chat-native cleanup block not found")
text = text.replace(old_cleanup, new_cleanup, 1)

path.write_text(text, encoding="utf-8")
print("temporary patcher corrected")
