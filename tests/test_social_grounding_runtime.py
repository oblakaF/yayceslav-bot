import social_grounding_runtime


def test_colloquial_member_opinion_resolves_explicit_mention():
    assert (
        social_grounding_runtime.extract_member_opinion_target(
            "Че думаешь о @RedCrew88"
        )
        == "@RedCrew88"
    )
    assert (
        social_grounding_runtime.extract_member_opinion_target(
            "чё скажешь про @Dobry64?"
        )
        == "@Dobry64"
    )


def test_unrelated_mention_is_not_member_opinion_route():
    assert social_grounding_runtime.extract_member_opinion_target(
        "позови @RedCrew88 сюда"
    ) is None


def test_target_evidence_contains_only_bounded_observed_profile_fields():
    evidence = social_grounding_runtime.build_target_evidence(
        "@RedCrew88",
        {
            "current_display_name": "Red Crew",
            "total_messages": 380,
            "replies_to_bot": 12,
            "insults_to_bot": 1,
            "current_title": "Владелец Золотого Тюбика",
            "self_reported_facts": [],
            "callback_terms": ["давай", "компьютер"],
        },
    )
    assert "380" in evidence
    assert "давай" in evidence
    assert "лезет в каждый спор" not in evidence
    assert "все это видят" not in evidence


def test_grounding_rules_do_not_treat_bot_previous_claims_as_evidence():
    rules = social_grounding_runtime._FINAL_GROUNDING_RULES
    compact = " ".join(rules.split())
    assert "Предыдущие ответы самого Яйцеслава" in compact
    assert "НЕ независимое доказательство" in compact
    assert "не нападай первым" in compact
