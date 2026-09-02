from types import SimpleNamespace

import canon_decision_runtime as decisions
import self_canon_runtime
import self_canon_v2_runtime


def test_everyday_car_choice_maps_to_transport():
    assert decisions.personal_choice_trait("Какую машину ты бы купил себе?") == "transport"


def test_everyday_city_choice_maps_to_residence():
    assert decisions.personal_choice_trait("Где бы ты жил, если выбирать для себя?") == "residence"


def test_operational_hypothetical_is_not_personal_canon():
    assert decisions.personal_choice_trait("Как бы ты исправил этот код?") is None
    assert decisions.personal_choice_trait("Как бы ты решил эту формулу?") is None


def test_temporary_role_does_not_activate_durable_choice_layer():
    assert decisions.personal_choice_trait("Представь, что ты пират на один день. Как бы ты одевался?") is None


def test_existing_target_trait_and_reason_are_exposed_as_current_choice(monkeypatch):
    bot_module = object()
    monkeypatch.setattr(
        self_canon_runtime,
        "load_canon_sync",
        lambda module, chat_id: {"transport": "Volvo XC60"},
    )
    monkeypatch.setattr(
        self_canon_v2_runtime,
        "_load_meta_sync",
        lambda module, chat_id: {
            "transport": {
                "reason": "мне ближе спокойная практичность и безопасность",
                "inertia": "medium",
                "commitment": 2,
            }
        },
    )

    context = decisions._decision_context(bot_module, 42, "transport")
    assert "Volvo XC60" in context
    assert "практичность" in context


def test_unset_target_trait_is_explicitly_first_choice(monkeypatch):
    monkeypatch.setattr(self_canon_runtime, "load_canon_sync", lambda module, chat_id: {})
    monkeypatch.setattr(self_canon_v2_runtime, "_load_meta_sync", lambda module, chat_id: {})

    context = decisions._decision_context(object(), 42, "music")
    assert "пока не установлена" in context
    assert "первый устойчивый выбор" in context


def test_prompt_enables_update_protocol_only_for_personal_choice(monkeypatch):
    decisions._INSTALLED = False

    def base_instruction(style_text="", user_settings=None, voice_style=False, chat_id=None, chat_type="private", user_name="", recent_messages=None, **kwargs):
        return "BASE"

    module = SimpleNamespace(build_full_system_instruction=base_instruction)
    monkeypatch.setattr(decisions, "_decision_context", lambda module, chat_id, trait_key: f"TARGET={trait_key}")

    assert decisions.install(module) is True
    personal = module.build_full_system_instruction(
        style_text="Какую машину ты бы купил себе?",
        chat_id=99,
    )
    assert "CANON-AWARE PERSONAL DECISION" in personal
    assert "TARGET=transport" in personal
    assert "SELF-CANON UPDATE PROTOCOL" in personal

    operational = module.build_full_system_instruction(
        style_text="Как бы ты исправил этот код?",
        chat_id=99,
    )
    assert operational == "BASE"

    decisions._INSTALLED = False


def test_mythic_core_is_not_a_mechanical_choice_constraint():
    assert "не обязан механически" in decisions._DECISION_RULE
    assert "машину" in decisions._DECISION_RULE
