import evidence_grounding_runtime as evidence


def test_live_proof_captions_are_detected():
    samples = (
        "Ты че ишак? Официальный сайт Рокстара посмотри",
        "Пруфы посмотри. Сайт Rockstar",
        "Вот скрин, проверь",
        "Ты ошибся, держи доказательство",
        "Где ссылка на источник?",
    )
    for text in samples:
        assert evidence.is_evidence_caption(text), text


def test_ordinary_photo_caption_is_not_forced_to_web():
    assert not evidence.is_evidence_caption("Что на фото?")
    assert not evidence.is_evidence_caption("Смешной мем")
    assert not evidence.is_evidence_caption("Смотри какая машина")


def test_terse_proof_followups_route_to_previous_topic_recovery():
    for text in (
        "Пруфы дай",
        "Проверь сначала",
        "официальный сайт покажи",
        "где ссылка",
    ):
        assert evidence.is_proof_text(text), text


def test_json_extraction_accepts_fenced_payload():
    payload = evidence._extract_json(
        '```json\n{"search_query":"GTA VI expanded showcase Rockstar Games 27 August 2026","visible_claims":["rockstargames.com"],"needs_web":true}\n```'
    )
    assert payload is not None
    assert payload["search_query"].startswith("GTA VI")
    assert payload["visible_claims"] == ["rockstargames.com"]


def test_grounding_prompt_makes_current_search_authoritative():
    prompt = evidence._grounding_prompt(
        "официальный сайт посмотри",
        ["rockstargames.com", "27 августа 2026", "26:48"],
        "Результат 1: Rockstar Games",
    )
    lowered = prompt.lower()
    assert "важнее предыдущих ответов" in lowered
    assert "исправь факт" in lowered
    assert "не называй screenshot фейком" in lowered
