from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    return text.replace(old, new, 1)


bot_path = Path("bot.py")
bot = bot_path.read_text(encoding="utf-8")

bot = replace_once(
    bot,
    '''    lowered = text.lower()\n\n    fresh_markers = (\n''',
    '''    lowered = text.lower()\n\n    # Короткие реплики-продолжения вроде «А сейчас?» сами по себе\n    # не являются запросом на свежие внешние данные. Иначе одно слово\n    # «сейчас» отправляет обычный reply-контекст в интернет-поиск.\n    normalized_followup = re.sub(\n        r"[^\\wёЁ]+",\n        " ",\n        lowered,\n        flags=re.UNICODE,\n    ).strip()\n    bare_freshness_followups = {\n        "сейчас",\n        "а сейчас",\n        "и сейчас",\n        "ну сейчас",\n        "ну а сейчас",\n        "ну и сейчас",\n        "сегодня",\n        "а сегодня",\n        "и сегодня",\n        "ну сегодня",\n        "ну а сегодня",\n        "ну и сегодня",\n        "на данный момент",\n        "а на данный момент",\n        "и на данный момент",\n        "прямо сейчас",\n        "а прямо сейчас",\n        "и прямо сейчас",\n    }\n    if normalized_followup in bare_freshness_followups:\n        return False\n\n    fresh_markers = (\n''',
    "bare freshness follow-up gate",
)

bot_path.write_text(bot, encoding="utf-8")


test_path = Path("tests/test_auto_search_gate.py")
tests = test_path.read_text(encoding="utf-8")

tests = replace_once(
    tests,
    '''    "ты думаешь, что ты умный?",\n]\n\nSHOULD_SEARCH = [\n''',
    '''    "ты думаешь, что ты умный?",\n    "А сейчас?",\n    "Сейчас?",\n    "И сейчас?",\n    "Ну а сейчас?",\n    "А сегодня?",\n    "Сегодня?",\n]\n\nSHOULD_SEARCH = [\n''',
    "bare follow-up regression cases",
)

tests = replace_once(
    tests,
    '''    "что произошло сегодня в Ханчжоу",\n]\n''',
    '''    "что произошло сегодня в Ханчжоу",\n    "какая погода сейчас в Тайбэе",\n]\n''',
    "freshness factual regression case",
)

test_path.write_text(tests, encoding="utf-8")
