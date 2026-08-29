import positive_engine
import whoami_dynamic_verdict
import monthly_memory_scope_patch as monthly


def test_sympathy_is_word_based_and_reputation_can_warm_neutral_affinity():
    score = positive_engine.sympathy_score(
        0,
        reputation_score=19,
        hostility_today=0,
    )
    assert score > 0
    assert positive_engine.sympathy_label(score) == "Доброжелательная"


def test_recent_positive_events_drive_sympathy_more_than_reputation_tilt():
    modest_rep = positive_engine.sympathy_score(12, reputation_score=10)
    high_rep_no_recent = positive_engine.sympathy_score(0, reputation_score=70)
    assert modest_rep > high_rep_no_recent
    assert positive_engine.sympathy_label(modest_rep) == "Тёплая"


def test_active_hostility_cools_public_sympathy_immediately():
    warm = positive_engine.sympathy_score(8, reputation_score=19, hostility_today=0)
    hostile = positive_engine.sympathy_score(8, reputation_score=19, hostility_today=3)
    assert hostile < warm
    assert positive_engine.sympathy_label(hostile) in {"Нейтральная", "Холодная", "Явная антипатия"}


def test_generic_frequent_words_are_not_monthly_topics():
    for word in ("вроде", "починил", "всех", "проверил", "кажется"):
        assert word in monthly._GENERIC_SINGLE_THEME_WORDS


def test_no_theme_verdict_is_grounded_in_real_dossier_signals():
    verdict = whoami_dynamic_verdict._fallback_verdict(
        2,
        "Доброжелательный",
        "Нейтрально",
    )
    assert "местн" in verdict.lower()
    assert "вроде" not in verdict.lower()
    assert "починил" not in verdict.lower()
