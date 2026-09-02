import asyncio
from types import SimpleNamespace

import legacy_character_retirement_runtime as runtime


class FakeButton:
    def __init__(self, text, callback_data):
        self.text = text
        self.callback_data = callback_data


class FakeMarkup:
    def __init__(self, rows):
        self.inline_keyboard = rows


def _fresh_module(monkeypatch, stored_character="chaos"):
    runtime._INSTALLED = False

    def get_user_settings_sync(user_id):
        assert user_id == 42
        return {
            "character": stored_character,
            "response_style": "bold",
            "response_length": "normal",
            "voice_enabled": False,
            "search_mode": "button",
            "roughness": "medium",
        }

    async def get_user_settings(user_id):
        return get_user_settings_sync(user_id)

    def build_settings_keyboard(settings):
        return FakeMarkup(
            [
                [FakeButton("Персонаж", "settings_character")],
                [FakeButton("Стиль", "settings_style")],
                [FakeButton("Длина", "settings_length")],
            ]
        )

    callback_calls = []

    async def settings_button_callback(update, context):
        callback_calls.append((update, context))

    module = SimpleNamespace(
        CHARACTER_LABELS={
            "classic": "🥚 Классический",
            "rus": "🗿 Древний рус",
            "professor": "🎓 Профессор",
            "chaos": "🤡 Безумный",
            "calm": "🧘 Спокойный",
        },
        InlineKeyboardMarkup=FakeMarkup,
        get_user_settings_sync=get_user_settings_sync,
        get_user_settings=get_user_settings,
        build_settings_keyboard=build_settings_keyboard,
        settings_button_callback=settings_button_callback,
    )
    return module, callback_calls


def test_normalize_settings_forces_single_effective_character():
    for legacy in ("rus", "professor", "chaos", "calm", "classic"):
        result = runtime.normalize_settings({"character": legacy, "roughness": "high"})
        assert result["character"] == "classic"
        assert result["roughness"] == "high"


def test_saved_legacy_character_is_ignored(monkeypatch):
    module, _ = _fresh_module(monkeypatch, "chaos")
    assert runtime.install(module) is True
    settings = module.get_user_settings_sync(42)
    assert settings["character"] == "classic"
    assert module.CHARACTER_LABELS["classic"] == "🥚 Яйцеслав"


def test_settings_keyboard_hides_character_row(monkeypatch):
    module, _ = _fresh_module(monkeypatch, "rus")
    runtime.install(module)
    keyboard = module.build_settings_keyboard({"character": "rus"})
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert "settings_character" not in callbacks
    assert callbacks == ["settings_style", "settings_length"]


def test_old_character_callback_is_gracefully_retired(monkeypatch):
    module, callback_calls = _fresh_module(monkeypatch, "professor")
    runtime.install(module)

    answers = []
    edited = []

    class Query:
        data = "settings_character"

        async def answer(self, text):
            answers.append(text)

        async def edit_message_reply_markup(self, reply_markup):
            edited.append(reply_markup)

    update = SimpleNamespace(
        callback_query=Query(),
        effective_user=SimpleNamespace(id=42),
    )
    asyncio.run(module.settings_button_callback(update, object()))

    assert callback_calls == []
    assert answers and "Яйцеслав теперь один" in answers[0]
    assert edited
    callbacks = [
        button.callback_data
        for row in edited[0].inline_keyboard
        for button in row
    ]
    assert "settings_character" not in callbacks


def test_non_character_callbacks_still_use_original_handler(monkeypatch):
    module, callback_calls = _fresh_module(monkeypatch)
    runtime.install(module)
    update = SimpleNamespace(
        callback_query=SimpleNamespace(data="settings_style"),
        effective_user=SimpleNamespace(id=42),
    )
    context = object()
    asyncio.run(module.settings_button_callback(update, context))
    assert callback_calls == [(update, context)]


def test_install_is_idempotent(monkeypatch):
    module, _ = _fresh_module(monkeypatch)
    assert runtime.install(module) is True
    loader = module.get_user_settings_sync
    keyboard = module.build_settings_keyboard
    callback = module.settings_button_callback
    assert runtime.install(module) is True
    assert module.get_user_settings_sync is loader
    assert module.build_settings_keyboard is keyboard
    assert module.settings_button_callback is callback
