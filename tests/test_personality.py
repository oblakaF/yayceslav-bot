import personality


def test_default_user_settings_has_expected_keys():
    expected = {
        "character",
        "response_style",
        "response_length",
        "voice_enabled",
        "search_mode",
        "roughness",
    }
    assert expected <= personality.DEFAULT_USER_SETTINGS.keys()


def test_voice_style_instruction_is_nonempty_string():
    assert isinstance(personality.VOICE_STYLE_INSTRUCTION, str)
    assert "голос" in personality.VOICE_STYLE_INSTRUCTION.lower()


def test_build_v2_base_instruction_reflects_detected_mode():
    instruction = personality.build_v2_base_instruction("привет, как дела?", None)
    assert "Яйцеслав" in instruction
    assert "Текущий режим общения: greeting" in instruction


def test_build_v2_base_instruction_serious_mode_suppresses_rudeness():
    instruction = personality.build_v2_base_instruction(
        "у меня умер родственник, что делать", None
    )
    assert "Текущий режим общения: serious" in instruction
