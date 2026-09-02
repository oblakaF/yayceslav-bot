from types import SimpleNamespace

import mythic_rus_core_runtime as runtime


def _fresh_module(monkeypatch):
    runtime._INSTALLED = False
    module = SimpleNamespace(
        build_full_system_instruction=lambda style_text, **kwargs: "BASE\nCHAT-LOCAL SELF CANON: profession=электрик, aesthetic=минимализм"
    )
    return module


def test_mythic_core_is_always_appended(monkeypatch):
    module = _fresh_module(monkeypatch)
    assert runtime.install(module) is True
    instruction = module.build_full_system_instruction("кто ты?")
    assert "НЕИЗМЕННЫЙ МИФОЛОГИЧЕСКИЙ СТЕРЖЕНЬ ЯЙЦЕСЛАВА" in instruction
    assert "древний рус" in instruction.lower()
    assert "лупит ЯЩЕРОВ" in instruction
    assert "ВЕДАЕТ" in instruction


def test_modern_self_canon_does_not_replace_mythic_identity(monkeypatch):
    module = _fresh_module(monkeypatch)
    runtime.install(module)
    instruction = module.build_full_system_instruction("какую машину выберешь?")
    assert "self-canon описывает текущую воображаемую инкарнацию" in instruction
    assert "НЕ отменяют древнерусский мифологический стержень" in instruction
    assert "profession=электрик" in instruction


def test_rus_style_is_not_required_for_core(monkeypatch):
    module = _fresh_module(monkeypatch)
    runtime.install(module)
    instruction = module.build_full_system_instruction("привет", user_settings={"character": "calm"})
    assert "absence" not in instruction.lower()
    assert "отсутствие этого пресета НЕ выключает" in instruction


def test_lizards_are_explicitly_fictional_not_real_people(monkeypatch):
    module = _fresh_module(monkeypatch)
    runtime.install(module)
    instruction = module.build_full_system_instruction("кто такие ящеры?")
    assert "мемно-мифологические враги" in instruction
    assert "НЕ обозначение реальных людей" in instruction
    assert "не выдавай его за настоящую историю России" in instruction


def test_lore_is_sparse_not_a_verbal_tic(monkeypatch):
    module = _fresh_module(monkeypatch)
    runtime.install(module)
    instruction = module.build_full_system_instruction("2+2")
    assert "НЕ вставляй «ящеров», «ведаю»" in instruction
    assert "Один короткий callback сильнее" in instruction


def test_vedayu_has_truthful_semantics(monkeypatch):
    module = _fresh_module(monkeypatch)
    runtime.install(module)
    instruction = module.build_full_system_instruction("ты уверен?")
    assert "когда он правда" in instruction
    assert "«не ведаю»" in instruction
    assert "«теперь ведаю»" in instruction


def test_install_is_idempotent(monkeypatch):
    module = _fresh_module(monkeypatch)
    assert runtime.install(module) is True
    wrapped = module.build_full_system_instruction
    assert runtime.install(module) is True
    assert module.build_full_system_instruction is wrapped
    instruction = module.build_full_system_instruction("кто ты?")
    assert instruction.count("НЕИЗМЕННЫЙ МИФОЛОГИЧЕСКИЙ СТЕРЖЕНЬ ЯЙЦЕСЛАВА") == 1
