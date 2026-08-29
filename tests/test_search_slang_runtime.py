from types import SimpleNamespace

import search_slang_runtime


def test_slang_proof_phrases_trigger_previous_topic_search():
    samples = (
        "пруфани",
        "пруфни",
        "а пруфы где?",
        "дай пруф",
        "покажи пруфы",
        "а не пиздишь?",
        "ты не врёшь?",
        "не гонишь?",
        "пахнет пиздежом",
        "пахнет явным пиздёжом",
        "это пиздеж?",
        "не выдумал?",
        "не придумал?",
        "уверен?",
        "ты уверен?",
        "точно?",
        "точняк?",
        "серьёзно?",
        "без пиздежа?",
        "пруфы?",
        "источники?",
        "ссылки?",
    )
    for text in samples:
        assert search_slang_runtime.is_slang_proof_request(text), text


def test_skeptic_words_inside_normal_sentences_do_not_force_search():
    samples = (
        "я уверен что завтра приду",
        "он точно сказал что придет",
        "это серьёзно меняет ситуацию",
        "ссылки на меню лежат сверху",
        "источники питания отключили",
    )
    for text in samples:
        assert not search_slang_runtime.is_slang_proof_request(text), text


def test_install_preserves_existing_search_extractor_and_adds_slang():
    search_slang_runtime._INSTALLED = False

    def original(text):
        if text == "проверь в интернете кота":
            return "кота"
        return None

    module = SimpleNamespace(extract_search_query=original)
    assert search_slang_runtime.install(module) is True

    assert module.extract_search_query("проверь в интернете кота") == "кота"
    assert module.extract_search_query("пруфани") == ""
    assert module.extract_search_query("а не пиздишь?") == ""
    assert module.extract_search_query("уверен?") == ""
    assert module.extract_search_query("я уверен что завтра приду") is None


def test_install_is_idempotent():
    search_slang_runtime._INSTALLED = False
    module = SimpleNamespace(extract_search_query=lambda text: None)

    assert search_slang_runtime.install(module) is True
    wrapped = module.extract_search_query
    assert search_slang_runtime.install(module) is True
    assert module.extract_search_query is wrapped
