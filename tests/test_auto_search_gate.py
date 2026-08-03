import bot

# Реальная фраза из Telegram, которая ошибочно запускала интернет-поиск:
# слово "сейчас" внутри "сделаю умнее чем сейчас" срабатывало как
# should_auto_search()-маркер, хотя сообщение — просто подкол боту.
ORIGINAL_TELEGRAM_PHRASE = (
    "может через месяцок попробую научить @BOBR_KURWWA_bot делать "
    "картинки и сделаю умнее чем сейчас, а то ты туповат пока да?"
)

SHOULD_NOT_SEARCH = [
    ORIGINAL_TELEGRAM_PHRASE,
    "может через месяц научу тебя делать картинки и сделаю умнее",
    "ты пока туповат",
    "я тебя ещё научу нормально отвечать",
    "когда-нибудь сделаю тебя умнее, понял?",
    "бот, ты вообще умеешь думать?",
    "ну ты и эксперт конечно",
    "я завтра начну учиться",
    "вот бы стать умнее",
    "как же ты меня достал",
    "ты думаешь, что ты умный?",
]

SHOULD_SEARCH = [
    "найди статьи о развитии интеллекта",
    "поищи в интернете, как улучшить память",
    "проверь, правда ли кофе обезвоживает",
    "какие сегодня новости об OpenAI",
    "кто сейчас президент Франции",
    "сколько сейчас стоит биткоин",
    "найди официальный сайт компании",
    "что произошло сегодня в Ханчжоу",
]


def _would_auto_search(text: str) -> bool:
    """Повторяет решение из answer_text_message для search_mode='auto'."""

    explicit = bot.extract_search_query(text)

    if explicit is not None:
        return True

    return (
        not bot.is_conversation_about_bot(text)
        and bot.should_auto_search(text)
    )


def test_conversational_and_meta_bot_phrases_do_not_trigger_search():
    for text in SHOULD_NOT_SEARCH:
        assert not _would_auto_search(text), text


def test_genuine_information_requests_still_trigger_search():
    for text in SHOULD_SEARCH:
        assert _would_auto_search(text), text


def test_original_telegram_phrase_is_blocked_by_the_bot_reference_gate():
    # Убеждаемся, что фраза блокируется именно новым предохранителем,
    # а не потому, что should_auto_search вдруг перестал видеть маркер.
    assert bot.should_auto_search(ORIGINAL_TELEGRAM_PHRASE)
    assert bot.is_conversation_about_bot(ORIGINAL_TELEGRAM_PHRASE)
    assert not _would_auto_search(ORIGINAL_TELEGRAM_PHRASE)


def test_explicit_search_triggers_are_unaffected_by_the_new_gate():
    explicit_phrases = [
        "найди статьи о развитии интеллекта",
        "поищи в интернете, как улучшить память",
        "проверь, правда ли кофе обезвоживает",
        "найди официальный сайт компании",
    ]

    for text in explicit_phrases:
        assert bot.extract_search_query(text) is not None, text


def test_button_search_mode_never_auto_searches_regardless_of_content():
    # search_mode="button" не должен вообще доходить до этой ветки —
    # проверяем это на уровне того же булева выражения, что в
    # answer_text_message: там есть "and search_mode == 'auto'".
    search_mode = "button"
    text = "кто сейчас президент Франции"

    explicit = bot.extract_search_query(text)
    auto_would_fire = (
        explicit is None
        and search_mode == "auto"
        and not bot.is_conversation_about_bot(text)
        and bot.should_auto_search(text)
    )

    assert explicit is None
    assert not auto_would_fire


def test_is_conversation_about_bot_false_for_plain_factual_questions():
    for text in SHOULD_SEARCH:
        assert not bot.is_conversation_about_bot(text), text
