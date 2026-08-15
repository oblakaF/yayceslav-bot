# ============================================================
# YAICESLAV V2 VOICE RUNTIME
#
# Берёт ОДИН уже выбранный voice pack и строит из него подсказку.
# Ни одного обращения/панча из другого пакета сюда попасть не может.
# ============================================================

from __future__ import annotations

import random
from dataclasses import dataclass

import voice_packs


@dataclass(frozen=True)
class VoiceMaterial:
    pack_name: str
    primary: str | None = None
    secondary: str | None = None
    category: str | None = None


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


def choose_voice_material(
    pack_name: str,
    *,
    conversation_mode: str = "normal",
    roughness: str = "medium",
    serious_topic: bool = False,
    rng=random,
) -> VoiceMaterial:
    pack = voice_packs.get_voice_pack(pack_name)

    if serious_topic or conversation_mode == "serious" or pack.name == "classic":
        return VoiceMaterial(pack_name=pack.name)

    primary: str | None = None
    secondary: str | None = None
    category: str | None = None

    if conversation_mode == "greeting":
        primary = _pick(pack.greetings or pack.slang, rng=rng)
        category = "greeting"
        if rng.random() < 0.28:
            secondary = _pick_distinct(primary, pack.addresses, rng=rng)

    elif conversation_mode == "hostile":
        primary = _pick(pack.comebacks or pack.taunts, rng=rng)
        category = "comeback"
        if roughness == "high" and rng.random() < 0.62:
            secondary = _pick_distinct(primary, pack.rough, rng=rng)

    elif conversation_mode == "challenge":
        primary = _pick(pack.taunts or pack.comebacks, rng=rng)
        category = "taunt"
        if roughness == "high" and rng.random() < 0.48:
            secondary = _pick_distinct(primary, pack.rough, rng=rng)

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
    )


def build_voice_instruction(material: VoiceMaterial) -> str:
    """Строит инструкцию, которая физически фиксирует один пакет."""

    lines = [
        "",
        "Речевой пакет этого ответа: " + material.pack_name + ".",
        (
            "ЖЁСТКОЕ ПРАВИЛО V2: используй только этот речевой пакет. "
            "Не добавляй слова, мемы, обращения или манеру из других пакетов."
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
