import owner_social_diagnostics_runtime as diag
import social_priority_runtime as social


def test_why_band_matches_social_priority_thresholds():
    trusted = social.RelationshipSnapshot(reputation_score=40)
    assert social.resolve_relationship_band(trusted) == "trusted"
    assert ">= +35" in diag._why_band(trusted, "trusted")

    feud = social.RelationshipSnapshot(
        reputation_score=-20,
        relationship_level=2,
        insults_to_bot=3,
    )
    assert social.resolve_relationship_band(feud) == "feuding_familiar"
    assert "конфликт" in diag._why_band(feud, "feuding_familiar")


def test_format_report_is_read_only_summary_without_raw_memory_terms():
    profile = {
        "reputation_score": 15,
        "positive_affinity_level": 1,
        "positive_affinity_points_30d": 6,
        "positive_streak": 2,
        "relationship_level": 2,
        "chat_level": 1,
        "replies_to_bot": 7,
        "insults_to_bot": 0,
        "reputation_positive_events": 3,
        "reputation_negative_events": 0,
        "total_messages": 45,
        "total_voice_messages": 4,
        "callback_terms": ["секретный_терм", "второй_терм"],
    }
    report = diag._format_report("Серега", 42, profile)
    assert "Relationship band: friendly" in report
    assert "Репутация: +15/100" in report
    assert "Callback memory terms: 2" in report
    assert "секретный_терм" not in report
    assert "ничего не меняет" in report
