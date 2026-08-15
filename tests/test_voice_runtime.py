import random

import voice_packs
import voice_runtime


def test_serious_topic_returns_no_styled_material():
    material = voice_runtime.choose_voice_material(
        "blat",
        conversation_mode="hostile",
        roughness="high",
        serious_topic=True,
        rng=random.Random(1),
    )
    assert material.pack_name == "blat"
    assert material.primary is None
    assert material.secondary is None


def test_blat_material_comes_only_from_blat_pack():
    rng = random.Random(123)
    pack = voice_packs.BLAT
    allowed = set(
        pack.slang
        + pack.addresses
        + pack.greetings
        + pack.taunts
        + pack.rough
        + pack.flex
        + pack.comebacks
        + pack.wisdoms
        + pack.grumbling
        + pack.praise
        + pack.comparisons
    )

    for _ in range(50):
        material = voice_runtime.choose_voice_material(
            "blat",
            conversation_mode="normal",
            roughness="high",
            rng=rng,
        )
        if material.primary:
            assert material.primary in allowed
        if material.secondary:
            assert material.secondary in allowed


def test_operative_instruction_marks_it_as_parody():
    material = voice_runtime.VoiceMaterial(
        pack_name="operative",
        primary="Материал подшит.",
    )
    instruction = voice_runtime.build_voice_instruction(material)
    assert "пародия" in instruction
    assert "не утверждай" in instruction.lower()


def test_battle_instruction_forbids_long_quotes():
    material = voice_runtime.VoiceMaterial(
        pack_name="battle_2017",
        primary="изи-изи",
    )
    instruction = voice_runtime.build_voice_instruction(material)
    assert "длинные чужие" in instruction


def test_post_irony_instruction_does_not_explain_joke():
    material = voice_runtime.VoiceMaterial(
        pack_name="post_irony",
        primary="Ситуация штатная.",
    )
    instruction = voice_runtime.build_voice_instruction(material)
    assert "Не объясняй" in instruction
    assert "шучу" in instruction


def test_classic_pack_has_no_special_material():
    material = voice_runtime.choose_voice_material(
        "classic",
        conversation_mode="normal",
        roughness="high",
        rng=random.Random(5),
    )
    assert material.primary is None
    instruction = voice_runtime.build_voice_instruction(material)
    assert "без специальной стилизации" in instruction
