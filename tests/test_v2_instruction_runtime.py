import bot
import style_engine


def test_v2_instruction_has_exactly_one_voice_pack_guard():
    style_engine.reset_length_history()
    instruction = bot.build_full_system_instruction(
        "что думаешь об этом?", chat_id=91001, chat_type="group"
    )
    assert instruction.count("Речевой пакет этого ответа:") == 1
    assert "Не смешивай" in instruction


def test_v2_instruction_uses_dynamic_length_block():
    style_engine.reset_length_history()
    instruction = bot.build_full_system_instruction("ну что?", chat_id=91002)
    assert "Динамическая длина этого конкретного ответа" in instruction
    assert "ориентир около" in instruction


def test_v2_base_does_not_emit_old_mixed_dictionary_sections():
    instruction = bot.build_full_system_instruction("привет", chat_id=91003)
    assert "Разрешённый сленг для этого ответа" not in instruction
    assert "Разрешённое старинное слово" not in instruction


def test_v2_serious_forces_classic_pack():
    instruction = bot.build_full_system_instruction("у меня умер родственник", chat_id=91004)
    assert "Речевой пакет этого ответа: classic" in instruction
    assert "пародия на казённо-оперативную речь" not in instruction


def test_v2_length_history_changes_per_chat_without_crash():
    style_engine.reset_length_history()
    for _ in range(4):
        bot.build_full_system_instruction("короткий вопрос", chat_id=91005)
    assert len(style_engine.get_length_history(91005)) == 4
