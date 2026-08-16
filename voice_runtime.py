# ============================================================
# YAICESLAV V2 VOICE RUNTIME
#
# Берёт ОДИН уже выбранный voice pack и строит из него подсказку.
# Ни одного обращения/панча из другого пакета сюда попасть не может.
# ============================================================

from __future__ import annotations

import random
from dataclasses import dataclass

import verdict_engine
import voice_packs


CONFLICT_TAUNT_CHANCE = 0.20
CONFLICT_SECOND_ELEMENT_CHANCE = 0.10
LAYERED_JOKE_CHANCE_WITHIN_TAUNT = 0.25

# Поведенческие СТРУКТУРЫ, а не отдельный словарь/voice pack.
# Лексика всё равно берётся только из уже выбранного пакета.
LAYERED_JOKE_PATTERNS = (
    "бытовой вопрос -> короткая пауза -> грубая причина, связанная с собеседником",
    "ложная забота о какой-то проблеме -> внезапный грубый диагноз/вывод",
    "как будто принёс или подарил что-то -> во второй части переверни подарок в оскорбительный ярлык",
    "почти нормальный комплимент -> резкий переворот смысла в последней фразе",
    "короткая загадка или вопрос с очевидным ответом -> ответ оказывается оскорбительным панчем",
    "нейтральное бытовое наблюдение -> неожиданный вывод, что причина в собеседнике",
    "псевдоопределение слова/явления -> в конце подставь собеседника как пример",
    "вежливое начало будто сейчас поможешь -> резко закончи одним грубым посылом",
    "два безобидных варианта выбора -> оба сходятся в одном коротком панче",
    "мини-история на одну фразу -> последняя короткая фраза переосмысляет её как оскорбление",
)


@dataclass(frozen=True)
class VoiceMaterial:
    pack_name: str
    primary: str | None = None
    secondary: str | None = None
    category: str | None = None
    verdict: str | None = None
    suppress_extra_taunt: bool = False
    layered_joke_pattern: str | None = None


def _pick(pool: tuple[str, ...], *, rng=random) -> str | None:
    if not pool:
        return None
    return rng.choice(pool)


def _pick_distinct(
    first: str | None,
    pool: tuple[str, ...],
    *,
    rng=random,
) -> str | None:
    if not pool:
        return None
    candidates = [item for item in pool if item != first]
    if not candidates:
        return None
    return rng.choice(candidates)


def _pick_non_taunt_conflict_material(
    pack: voice_packs.VoicePack,
    *,
    roughness: str,
    rng=random,
) -> tuple[str | None, str | None]:
    """Даёт грубость/характер без обязательной насмешки."""

    if roughness == "high" and pack.rough:
        return _pick(pack.rough, rng=rng), "rough"

    if pack.slang:
        return _pick(pack.slang, rng=rng), "slang"

    if pack.comparisons:
        return _pick(pack.comparisons, rng=rng), "comparison"

    return None, None


def choose_voice_material(
    pack_name: str,
    *,
    conversation_mode: str = "normal",
    roughness: str = "medium",
    serious_topic: bool = False,
    adaptation: dict | None = None,
    rng=random,
) -> VoiceMaterial:
    pack = voice_packs.get_voice_pack(pack_name)

    if serious_topic or conversation_mode == "serious" or pack.name == "classic":
        return VoiceMaterial(pack_name=pack.name)

    adaptation = adaptation or {}
    taunt_chance = max(0.12, min(0.28, CONFLICT_TAUNT_CHANCE * float(adaptation.get("taunt_multiplier", 1.0))))
    layered_chance = max(0.15, min(0.35, LAYERED_JOKE_CHANCE_WITHIN_TAUNT * float(adaptation.get("layered_multiplier", 1.0))))
    verdict_multiplier = max(0.85, min(1.15, float(adaptation.get("verdict_multiplier", 1.0))))

    primary: str | None = None
    secondary: str | None = None
    category: str | None = None
    verdict: str | None = None
    suppress_extra_taunt = False
    layered_joke_pattern: str | None = None

    if conversation_mode == "greeting":
        primary = _pick(pack.greetings or pack.slang, rng=rng)
        category = "greeting"
        if rng.random() < 0.28:
            secondary = _pick_distinct(primary, pack.addresses, rng=rng)

    elif conversation_mode in {"hostile", "challenge"}:
        taunt_selected = rng.random() < taunt_chance

        if taunt_selected:
            # Многослойный setup→punchline — редкий ПОДТИП уже разрешённого
            # taunt, а не ещё один независимый генератор. 20% * 25% = ~5%
            # всех конфликтных ответов. Проверка через верхнюю четверть
            # сохраняет старые deterministic ZeroRng-тесты обычного taunt.
            layered_selected = (
                rng.random() >= (1.0 - layered_chance)
            )

            if layered_selected:
                category = "layered_taunt"
                layered_joke_pattern = _pick(
                    LAYERED_JOKE_PATTERNS,
                    rng=rng,
                )
                # Для многослойного панча даём только лексический оттенок
                # текущего пакета. Второй элемент запрещён.
                primary = _pick(pack.rough or pack.slang, rng=rng)
                secondary = None
            else:
                if conversation_mode == "hostile":
                    primary = _pick(pack.comebacks or pack.taunts, rng=rng)
                    category = "comeback"
                else:
                    primary = _pick(pack.taunts or pack.comebacks, rng=rng)
                    category = "taunt"

                # Даже когда taunt разрешён, не устраиваем двойной панч почти всегда.
                if (
                    roughness == "high"
                    and rng.random() < CONFLICT_SECOND_ELEMENT_CHANCE
                ):
                    secondary = _pick_distinct(primary, pack.rough, rng=rng)
        else:
            primary, category = _pick_non_taunt_conflict_material(
                pack,
                roughness=roughness,
                rng=rng,
            )
            suppress_extra_taunt = True

        verdict = verdict_engine.choose_verdict(
            conversation_mode,
            taunt_already_selected=taunt_selected,
            chance_multiplier=verdict_multiplier,
            rng=rng,
        )

    else:
        category_pools = [
            ("slang", pack.slang),
            ("wisdom", pack.wisdoms),
            ("comparison", pack.comparisons),
            ("praise", pack.praise),
            ("grumbling", pack.grumbling),
            ("flex", pack.flex),
        ]

        if roughness == "high":
            category_pools.extend(
                [
                    ("taunt", pack.taunts),
                    ("rough", pack.rough),
                ]
            )

        available = [(name, pool) for name, pool in category_pools if pool]
        if available:
            category, pool = rng.choice(available)
            primary = _pick(pool, rng=rng)

        # Второй элемент — не всегда. Он берётся из ТОГО ЖЕ пакета.
        if primary and rng.random() < 0.24:
            followup_pool = pack.addresses if pack.addresses else pack.slang
            secondary = _pick_distinct(primary, followup_pool, rng=rng)

    return VoiceMaterial(
        pack_name=pack.name,
        primary=primary,
        secondary=secondary,
        category=category,
        verdict=verdict,
        suppress_extra_taunt=suppress_extra_taunt,
        layered_joke_pattern=layered_joke_pattern,
    )


def build_voice_instruction(material: VoiceMaterial) -> str:
    """Строит инструкцию, которая физически фиксирует один пакет."""

    lines = [
        "",
        "Речевой пакет этого ответа: " + material.pack_name + ".",
        (
            "ЖЁСТКОЕ ПРАВИЛО V2: используй только этот речевой пакет. "
            "Не смешивай его с другими пакетами и не добавляй их слова, мемы, обращения или манеру."
        ),
    ]

    if material.pack_name == "classic":
        lines.append(
            "Отвечай обычным голосом Яйцеслава без специальной стилизации."
        )
        return "\n".join(lines)

    if material.primary:
        lines.append(
            "Материал этого пакета для вдохновения: " + repr(material.primary) + "."
        )

    if material.secondary:
        lines.append(
            "Допустимый второй элемент ТОГО ЖЕ пакета: "
            + repr(material.secondary)
            + "."
        )

    if material.layered_joke_pattern:
        lines.append(
            "МНОГОСЛОЙНАЯ ШУТКА: это ОДИН панч, построенный в два-три коротких хода. "
            "Сначала дай почти нормальный setup, затем короткую паузу/поворот и только в конце грубую развязку. "
            "Структура на этот раз: " + repr(material.layered_joke_pattern) + ". "
            "Не копируй готовые известные шутки и не повторяй одну формулу дословно. "
            "После развязки СТОП: никакого второго taunt, verdict, пояснения шутки или дополнительного добивания."
        )
    elif material.suppress_extra_taunt:
        lines.append(
            "В ЭТОМ ответе не добавляй отдельную насмешку, taunt или второй добивающий панч. "
            "Если пользователь прямо оскорбил тебя, естественный вариант — просто коротко и матерно его отбрить/послать "
            "одной фразой без шутки. Ответ уровня «иди нахуй», «отъебись» или столь же короткий прямой посыл "
            "сам по себе является ПОЛНЫМ ответом — не объясняй его, не добавляй второй абзац и не продолжай после него. "
            "Можно быть грубым, матерным и резким по смыслу, но после основного ответа остановись."
        )
    elif material.category in {"taunt", "comeback"}:
        lines.append(
            "В этом ответе разрешён максимум ОДИН короткий подкол. После него не дожимай человека второй насмешкой."
        )

    if material.verdict:
        lines.append(
            "В самом конце добавь ОДИН короткий человеческий хвост-вердикт: "
            + repr(material.verdict)
            + ". Не объясняй его и ничего не добавляй после него. Это не второй taunt."
        )

    lines.append(
        "Не обязан вставлять фразы дословно. Сохрани их манеру и не превращай "
        "ответ в набор цитат. Максимум два стилистических элемента."
    )

    if material.pack_name == "operative":
        lines.append(
            "Это очевидная пародия на казённо-оперативную речь. Не утверждай, "
            "что реально связан со спецслужбами, следишь за человеком или куда-то "
            "передаёшь его данные."
        )

    if material.pack_name == "battle_2017":
        lines.append(
            "Короткие мемные референсы допустимы; длинные чужие баттл-строки "
            "не цитируй. Основной панч формулируй самостоятельно."
        )

    if material.pack_name == "post_irony":
        lines.append(
            "Не объясняй, что это постирония, и не добавляй обязательное «шучу». "
            "Сухой серьёзный тон — часть эффекта."
        )

    return "\n".join(lines)
