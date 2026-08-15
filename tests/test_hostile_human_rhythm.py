import bot
import humor_engine
import verdict_engine
import voice_runtime


class SequenceRng:
    def __init__(self, values):
        self.values = list(values)

    def random(self):
        if not self.values:
            return 0.99
        return self.values.pop(0)

    @staticmethod
    def choice(seq):
        return seq[0]


def setup_function():
    verdict_engine.reset_recent()


def test_total_conflict_comedy_gate_is_twenty_percent():
    assert voice_runtime.CONFLICT_TAUNT_CHANCE == 0.20


def test_layered_joke_is_quarter_of_taunt_gate_about_five_percent_total():
    assert voice_runtime.LAYERED_JOKE_CHANCE_WITHIN_TAUNT == 0.25
    assert (
        voice_runtime.CONFLICT_TAUNT_CHANCE
        * voice_runtime.LAYERED_JOKE_CHANCE_WITHIN_TAUNT
        == 0.05
    )


def test_layered_hostile_joke_has_no_verdict_or_second_element():
    # 0.0 -> taunt gate opens; 0.99 -> upper quarter => layered subtype.
    material = voice_runtime.choose_voice_material(
        "blat",
        conversation_mode="hostile",
        roughness="high",
        rng=SequenceRng([0.0, 0.99]),
    )
    assert material.category == "layered_taunt"
    assert material.layered_joke_pattern
    assert material.secondary is None
    assert material.verdict is None

    instruction = voice_runtime.build_voice_instruction(material)
    assert "МНОГОСЛОЙНАЯ ШУТКА" in instruction
    assert "никакого второго taunt" in instruction
    assert "После развязки СТОП" in instruction


def test_plain_hostile_reply_explicitly_allows_simple_sendoff_without_joke():
    material = voice_runtime.choose_voice_material(
        "blat",
        conversation_mode="hostile",
        roughness="high",
        rng=SequenceRng([0.99, 0.99]),
    )
    assert material.suppress_extra_taunt
    assert material.category == "rough"
    instruction = voice_runtime.build_voice_instruction(material)
    assert "коротко и матерно его отбрить/послать" in instruction
    assert "без шутки" in instruction


def test_bot_hostile_runtime_does_not_call_legacy_second_banter(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("legacy decide_banter must not run in V2 hostile path")

    monkeypatch.setattr(bot.humor_engine, "decide_banter", fail)
    instruction = bot.build_full_system_instruction(
        "ты мудак",
        chat_id=90901,
        chat_type="group",
        user_id=101,
        bot_was_mentioned=True,
    )
    assert "V2 character state: hostile_response" in instruction


def test_legacy_banter_helper_still_exists_for_explicit_uses():
    # Мы не удаляем helper из API модуля — просто не наслаиваем его
    # автоматически поверх единственного voice_runtime taunt gate.
    assert callable(humor_engine.decide_banter)
