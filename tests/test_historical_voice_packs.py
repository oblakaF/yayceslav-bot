import random

import style_engine
import voice_packs
import voice_runtime


def test_historical_packs_are_registered_as_separate_styles():
    expected = {"runet_2007", "runet_2012_2016", "lan_2000s"}
    assert expected <= set(style_engine.VOICE_PACKS)
    assert expected <= set(voice_packs.VOICE_PACKS)


def test_runet_2007_material_never_comes_from_lan_pack():
    rng = random.Random(404)
    runet = voice_packs.RUNET_2007
    lan = voice_packs.LAN_2000S
    runet_allowed = set(
        runet.slang + runet.addresses + runet.greetings + runet.taunts + runet.rough
        + runet.flex + runet.comebacks + runet.wisdoms + runet.grumbling + runet.praise + runet.comparisons
    )
    lan_only = set(lan.slang + lan.taunts) - runet_allowed
    assert lan_only
    for _ in range(60):
        material = voice_runtime.choose_voice_material(
            "runet_2007", conversation_mode="normal", roughness="high", rng=rng
        )
        if material.primary:
            assert material.primary in runet_allowed
            assert material.primary not in lan_only
        if material.secondary:
            assert material.secondary in runet_allowed


def test_serious_mode_still_forces_classic_after_historical_addition():
    ctx = style_engine.VoicePackContext(
        conversation_mode="serious", selected_character="chaos", serious_topic=True
    )
    assert style_engine.choose_voice_pack(ctx, rng=random.Random(1)) == "classic"


def test_historical_weights_exist_only_as_independent_choices():
    normal = style_engine._VOICE_PACK_WEIGHTS_BY_MODE["normal"]
    assert normal["runet_2007"] > 0
    assert normal["runet_2012_2016"] > 0
    assert normal["lan_2000s"] > 0


def test_russian_internet_classics_are_wired_as_own_pack():
    assert "runet_classic" in style_engine.VOICE_PACKS
    pack = voice_packs.VOICE_PACKS["runet_classic"]
    assert pack.slang
    assert any("карму" in item or "форум" in item or "баян" in item for item in pack.slang)


def test_runet_classic_is_not_merged_into_runet_2007():
    classic = voice_packs.VOICE_PACKS["runet_classic"]
    era_2007 = voice_packs.VOICE_PACKS["runet_2007"]
    assert classic is not era_2007
    assert classic.name != era_2007.name
