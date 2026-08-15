import random

import verdict_engine
import voice_packs
import voice_runtime


class ZeroRng:
    @staticmethod
    def random():
        return 0.0

    @staticmethod
    def choice(seq):
        return seq[0]


class HighRng:
    @staticmethod
    def random():
        return 0.99

    @staticmethod
    def choice(seq):
        return seq[0]


def setup_function():
    verdict_engine.reset_recent()


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
    assert material.verdict is None


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


def test_conflict_taunt_probability_constant_is_twenty_percent():
    assert voice_runtime.CONFLICT_TAUNT_CHANCE == 0.20


def test_challenge_can_select_one_taunt_when_roll_is_low():
    material = voice_runtime.choose_voice_material(
        "blat",
        conversation_mode="challenge",
        roughness="high",
        rng=ZeroRng(),
    )
    assert material.category == "taunt"
    assert not material.suppress_extra_taunt
    assert material.verdict is None


def test_challenge_without_taunt_stays_rough_but_forbids_extra_mockery():
    material = voice_runtime.choose_voice_material(
        "blat",
        conversation_mode="challenge",
        roughness="high",
        rng=HighRng(),
    )
    assert material.category == "rough"
    assert material.primary in voice_packs.BLAT.rough
    assert material.suppress_extra_taunt

    instruction = voice_runtime.build_voice_instruction(material)
    assert "не добавляй отдельную насмешку" in instruction
    assert "Можно быть грубым, матерным и резким" in instruction


def test_hostile_without_taunt_does_not_force_comeback():
    material = voice_runtime.choose_voice_material(
        "skoof",
        conversation_mode="hostile",
        roughness="high",
        rng=HighRng(),
    )
    assert material.category == "rough"
    assert material.category != "comeback"
    assert material.suppress_extra_taunt


def test_verdict_and_taunt_are_mutually_exclusive():
    material = voice_runtime.choose_voice_material(
        "blat",
        conversation_mode="hostile",
        roughness="high",
        rng=ZeroRng(),
    )
    assert material.category == "comeback"
    assert material.verdict is None


def test_verdict_instruction_is_single_final_tail():
    material = voice_runtime.VoiceMaterial(
        pack_name="blat",
        primary="базар",
        category="rough",
        verdict="дебилы, бля.",
        suppress_extra_taunt=True,
    )
    instruction = voice_runtime.build_voice_instruction(material)
    assert "дебилы, бля." in instruction
    assert "ничего не добавляй после него" in instruction
    assert "Это не второй taunt" in instruction


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
    assert material.verdict is None
    instruction = voice_runtime.build_voice_instruction(material)
    assert "без специальной стилизации" in instruction
