from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1) voice_runtime: one single 20% conflict comedy gate,
#    with a 25% layered subtype => ~5% of all conflict replies.
replace_once(
    "voice_runtime.py",
    '''CONFLICT_TAUNT_CHANCE = 0.20\nCONFLICT_SECOND_ELEMENT_CHANCE = 0.10\n''',
    '''CONFLICT_TAUNT_CHANCE = 0.20\nCONFLICT_SECOND_ELEMENT_CHANCE = 0.10\nLAYERED_JOKE_CHANCE_WITHIN_TAUNT = 0.25\n\n# Поведенческие СТРУКТУРЫ, а не отдельный словарь/voice pack.\n# Лексика всё равно берётся только из уже выбранного пакета.\nLAYERED_JOKE_PATTERNS = (\n    "бытовой вопрос -> короткая пауза -> грубая причина, связанная с собеседником",\n    "ложная забота о какой-то проблеме -> внезапный грубый диагноз/вывод",\n    "как будто принёс или подарил что-то -> во второй части переверни подарок в оскорбительный ярлык",\n    "почти нормальный комплимент -> резкий переворот смысла в последней фразе",\n    "короткая загадка или вопрос с очевидным ответом -> ответ оказывается оскорбительным панчем",\n    "нейтральное бытовое наблюдение -> неожиданный вывод, что причина в собеседнике",\n    "псевдоопределение слова/явления -> в конце подставь собеседника как пример",\n    "вежливое начало будто сейчас поможешь -> резко закончи одним грубым посылом",\n    "два безобидных варианта выбора -> оба сходятся в одном коротком панче",\n    "мини-история на одну фразу -> последняя короткая фраза переосмысляет её как оскорбление",\n)\n''',
    "layered constants",
)

replace_once(
    "voice_runtime.py",
    '''    verdict: str | None = None\n    suppress_extra_taunt: bool = False\n''',
    '''    verdict: str | None = None\n    suppress_extra_taunt: bool = False\n    layered_joke_pattern: str | None = None\n''',
    "layered dataclass field",
)

replace_once(
    "voice_runtime.py",
    '''    verdict: str | None = None\n    suppress_extra_taunt = False\n\n    if conversation_mode == "greeting":\n''',
    '''    verdict: str | None = None\n    suppress_extra_taunt = False\n    layered_joke_pattern: str | None = None\n\n    if conversation_mode == "greeting":\n''',
    "layered local state",
)

replace_once(
    "voice_runtime.py",
    '''        if taunt_selected:\n            if conversation_mode == "hostile":\n                primary = _pick(pack.comebacks or pack.taunts, rng=rng)\n                category = "comeback"\n            else:\n                primary = _pick(pack.taunts or pack.comebacks, rng=rng)\n                category = "taunt"\n\n            # Даже когда taunt разрешён, не устраиваем двойной панч почти всегда.\n            if (\n                roughness == "high"\n                and rng.random() < CONFLICT_SECOND_ELEMENT_CHANCE\n            ):\n                secondary = _pick_distinct(primary, pack.rough, rng=rng)\n        else:\n''',
    '''        if taunt_selected:\n            # Многослойный setup→punchline — редкий ПОДТИП уже разрешённого\n            # taunt, а не ещё один независимый генератор. 20% * 25% = ~5%\n            # всех конфликтных ответов. Проверка через верхнюю четверть\n            # сохраняет старые deterministic ZeroRng-тесты обычного taunt.\n            layered_selected = (\n                rng.random() >= (1.0 - LAYERED_JOKE_CHANCE_WITHIN_TAUNT)\n            )\n\n            if layered_selected:\n                category = "layered_taunt"\n                layered_joke_pattern = _pick(\n                    LAYERED_JOKE_PATTERNS,\n                    rng=rng,\n                )\n                # Для многослойного панча даём только лексический оттенок\n                # текущего пакета. Второй элемент запрещён.\n                primary = _pick(pack.rough or pack.slang, rng=rng)\n                secondary = None\n            else:\n                if conversation_mode == "hostile":\n                    primary = _pick(pack.comebacks or pack.taunts, rng=rng)\n                    category = "comeback"\n                else:\n                    primary = _pick(pack.taunts or pack.comebacks, rng=rng)\n                    category = "taunt"\n\n                # Даже когда taunt разрешён, не устраиваем двойной панч почти всегда.\n                if (\n                    roughness == "high"\n                    and rng.random() < CONFLICT_SECOND_ELEMENT_CHANCE\n                ):\n                    secondary = _pick_distinct(primary, pack.rough, rng=rng)\n        else:\n''',
    "layered conflict selection",
)

replace_once(
    "voice_runtime.py",
    '''        verdict=verdict,\n        suppress_extra_taunt=suppress_extra_taunt,\n    )\n''',
    '''        verdict=verdict,\n        suppress_extra_taunt=suppress_extra_taunt,\n        layered_joke_pattern=layered_joke_pattern,\n    )\n''',
    "layered return field",
)

replace_once(
    "voice_runtime.py",
    '''    if material.suppress_extra_taunt:\n        lines.append(\n            "В ЭТОМ ответе не добавляй отдельную насмешку, taunt или второй добивающий панч. "\n            "Можно быть грубым, матерным и резким по смыслу, но после основного ответа остановись."\n        )\n    elif material.category in {"taunt", "comeback"}:\n''',
    '''    if material.layered_joke_pattern:\n        lines.append(\n            "МНОГОСЛОЙНАЯ ШУТКА: это ОДИН панч, построенный в два-три коротких хода. "\n            "Сначала дай почти нормальный setup, затем короткую паузу/поворот и только в конце грубую развязку. "\n            "Структура на этот раз: " + repr(material.layered_joke_pattern) + ". "\n            "Не копируй готовые известные шутки и не повторяй одну формулу дословно. "\n            "После развязки СТОП: никакого второго taunt, verdict, пояснения шутки или дополнительного добивания."\n        )\n    elif material.suppress_extra_taunt:\n        lines.append(\n            "В ЭТОМ ответе не добавляй отдельную насмешку, taunt или второй добивающий панч. "\n            "Если пользователь прямо оскорбил тебя, естественный вариант — просто коротко и матерно его отбрить/послать "\n            "одной фразой без шутки. Можно быть грубым, матерным и резким по смыслу, но после основного ответа остановись."\n        )\n    elif material.category in {"taunt", "comeback"}:\n''',
    "layered/simple hostile instruction",
)

# 2) bot.py: remove the SECOND independent hostile banter generator.
replace_once(
    "bot.py",
    '''        if conversation_mode == "hostile":\n            humor_decision = humor_engine.decide_banter(\n                humor_ctx,\n                tracker_chat_id,\n                tracker=humor_tracker,\n            )\n        else:\n''',
    '''        if conversation_mode == "hostile":\n            # В V2 конфликтный юмор централизован в voice_runtime: там один\n            # общий 20%-й шлюз. Не запускаем второй независимый banter-layer,\n            # иначе фактическая частота насмешек снова становится выше 20%.\n            humor_decision = humor_engine.HumorDecision(\n                humor_allowed=False\n            )\n        else:\n''',
    "disable second hostile banter layer",
)

# 3) Permanent regression tests.
Path("tests/test_hostile_human_rhythm.py").write_text(
    '''import bot\nimport humor_engine\nimport verdict_engine\nimport voice_runtime\n\n\nclass SequenceRng:\n    def __init__(self, values):\n        self.values = list(values)\n\n    def random(self):\n        if not self.values:\n            return 0.99\n        return self.values.pop(0)\n\n    @staticmethod\n    def choice(seq):\n        return seq[0]\n\n\ndef setup_function():\n    verdict_engine.reset_recent()\n\n\ndef test_total_conflict_comedy_gate_is_twenty_percent():\n    assert voice_runtime.CONFLICT_TAUNT_CHANCE == 0.20\n\n\ndef test_layered_joke_is_quarter_of_taunt_gate_about_five_percent_total():\n    assert voice_runtime.LAYERED_JOKE_CHANCE_WITHIN_TAUNT == 0.25\n    assert (\n        voice_runtime.CONFLICT_TAUNT_CHANCE\n        * voice_runtime.LAYERED_JOKE_CHANCE_WITHIN_TAUNT\n        == 0.05\n    )\n\n\ndef test_layered_hostile_joke_has_no_verdict_or_second_element():\n    # 0.0 -> taunt gate opens; 0.99 -> upper quarter => layered subtype.\n    material = voice_runtime.choose_voice_material(\n        "blat",\n        conversation_mode="hostile",\n        roughness="high",\n        rng=SequenceRng([0.0, 0.99]),\n    )\n    assert material.category == "layered_taunt"\n    assert material.layered_joke_pattern\n    assert material.secondary is None\n    assert material.verdict is None\n\n    instruction = voice_runtime.build_voice_instruction(material)\n    assert "МНОГОСЛОЙНАЯ ШУТКА" in instruction\n    assert "никакого второго taunt" in instruction\n    assert "После развязки СТОП" in instruction\n\n\ndef test_plain_hostile_reply_explicitly_allows_simple_sendoff_without_joke():\n    material = voice_runtime.choose_voice_material(\n        "blat",\n        conversation_mode="hostile",\n        roughness="high",\n        rng=SequenceRng([0.99, 0.99]),\n    )\n    assert material.suppress_extra_taunt\n    assert material.category == "rough"\n    instruction = voice_runtime.build_voice_instruction(material)\n    assert "коротко и матерно его отбрить/послать" in instruction\n    assert "без шутки" in instruction\n\n\ndef test_bot_hostile_runtime_does_not_call_legacy_second_banter(monkeypatch):\n    def fail(*args, **kwargs):\n        raise AssertionError("legacy decide_banter must not run in V2 hostile path")\n\n    monkeypatch.setattr(bot.humor_engine, "decide_banter", fail)\n    instruction = bot.build_full_system_instruction(\n        "ты мудак",\n        chat_id=90901,\n        chat_type="group",\n        user_id=101,\n        bot_was_mentioned=True,\n    )\n    assert "V2 character state: hostile_response" in instruction\n\n\ndef test_legacy_banter_helper_still_exists_for_explicit_uses():\n    # Мы не удаляем helper из API модуля — просто не наслаиваем его\n    # автоматически поверх единственного voice_runtime taunt gate.\n    assert callable(humor_engine.decide_banter)\n''',
    encoding="utf-8",
)
