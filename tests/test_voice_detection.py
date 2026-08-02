import bot


def test_text_requests_voice_positive():
    assert bot.text_requests_voice("расскажи анекдот, ответь голосом") is True
    assert bot.text_requests_voice("озвучь, пожалуйста") is True
    assert bot.text_requests_voice("скажи это голосом") is True


def test_text_requests_voice_negative_for_unrelated_golos_mention():
    assert bot.text_requests_voice("что делать с осипшим голосом?") is False
    assert bot.text_requests_voice("обычный текстовый вопрос про питон") is False


def test_remove_voice_request_strips_only_the_voice_phrase():
    cleaned = bot.remove_voice_request("расскажи анекдот, ответь голосом")
    assert "голосом" not in cleaned
    assert "анекдот" in cleaned


def test_remove_voice_request_does_not_touch_unrelated_golos_mention():
    original = "что делать с осипшим голосом?"
    cleaned = bot.remove_voice_request(original)
    assert "голосом" in cleaned
