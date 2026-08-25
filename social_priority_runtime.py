"""Authoritative relationship-first tone arbitration for Yayceslav.

The bot already has several useful social signals (lifetime reputation,
30-day positive affinity, familiarity, daily hostility and episodic memory),
but older personality/mood/media prompts can still pull the final tone in
conflicting directions. This late runtime does not add storage, background
workers or model calls. It only establishes one deterministic priority order
for text, voice/audio and video circles:

1. serious/safety context is always handled helpfully;
2. persistent reputation and sympathy choose the baseline attitude;
3. real relationship history may color that baseline;
4. the current message/media decides what to respond to;
5. generic character, roughness and chat mood are only final flavor.
"""

from __future__ import annotations

import functools
import logging
import sys
from dataclasses import dataclass
from typing import Any, Mapping


_INSTALLED = False
_GROUP_CHAT_TYPES = {"group", "supergroup"}

_PROACTIVE_VIDEO_MARKERS = (
    "тебя никто не звал",
    "сам решил вклиниться",
    "видео-кружок",
)
_VOICE_MEDIA_MARKERS = (
    "прослушай сообщение пользователя",
    "полную расшифровку не делай",
)


@dataclass(frozen=True)
class RelationshipSnapshot:
    reputation_score: int = 0
    positive_affinity_level: int = 0
    positive_affinity_points_30d: int = 0
    positive_streak: int = 0
    relationship_level: int = 0
    chat_level: int = 0
    hostility_today: int = 0
    insults_to_bot: int = 0
    reputation_negative_events: int = 0
    replies_to_bot: int = 0

    @property
    def familiarity(self) -> int:
        return max(self.relationship_level, self.chat_level)

    @property
    def has_repeated_conflict_history(self) -> bool:
        return bool(
            self.reputation_score <= -10
            or self.hostility_today > 0
            or self.reputation_negative_events >= 2
            or self.insults_to_bot >= 3
        )


def _safe_int(profile: Mapping[str, Any] | None, key: str, default: int = 0) -> int:
    if not profile:
        return int(default)
    try:
        return int(profile.get(key, default) or 0)
    except (TypeError, ValueError):
        return int(default)


def snapshot_from_profile(
    profile: Mapping[str, Any] | None,
) -> RelationshipSnapshot:
    """Read only already-available bounded profile fields; no extra DB query."""

    reputation = max(-100, min(100, _safe_int(profile, "reputation_score")))
    affinity_level = max(
        0,
        min(4, _safe_int(profile, "positive_affinity_level")),
    )
    relationship_level = max(
        0,
        min(4, _safe_int(profile, "relationship_level")),
    )
    chat_level = max(0, min(4, _safe_int(profile, "chat_level")))

    return RelationshipSnapshot(
        reputation_score=reputation,
        positive_affinity_level=affinity_level,
        positive_affinity_points_30d=max(
            0,
            _safe_int(profile, "positive_affinity_points_30d"),
        ),
        positive_streak=max(0, _safe_int(profile, "positive_streak")),
        relationship_level=relationship_level,
        chat_level=chat_level,
        hostility_today=max(0, _safe_int(profile, "hostility_today")),
        insults_to_bot=max(0, _safe_int(profile, "insults_to_bot")),
        reputation_negative_events=max(
            0,
            _safe_int(profile, "reputation_negative_events"),
        ),
        replies_to_bot=max(0, _safe_int(profile, "replies_to_bot")),
    )


def resolve_relationship_band(snapshot: RelationshipSnapshot) -> str:
    """Resolve the persistent attitude before looking at current wording."""

    # Strong recent sympathy can warm a neutral lifetime score, but it does
    # not magically erase a clearly negative long-term score.
    if snapshot.reputation_score >= 35 or (
        snapshot.reputation_score >= 0
        and snapshot.positive_affinity_level >= 3
    ):
        return "trusted"

    if snapshot.reputation_score >= 10 or (
        snapshot.reputation_score >= -9
        and snapshot.positive_affinity_level >= 1
    ):
        return "friendly"

    familiar = bool(
        snapshot.familiarity >= 2
        or snapshot.replies_to_bot >= 5
    )

    if snapshot.has_repeated_conflict_history:
        return "feuding_familiar" if familiar else "wary"

    if familiar:
        return "neutral_familiar"

    return "neutral"


def detect_media_kind(style_text: str) -> str:
    lowered = str(style_text or "").lower()
    if all(marker in lowered for marker in _PROACTIVE_VIDEO_MARKERS):
        return "proactive_video"
    if any(marker in lowered for marker in _VOICE_MEDIA_MARKERS):
        return "voice_or_audio"
    return "text"


def _neutral_style_text(media_kind: str) -> str:
    if media_kind == "proactive_video":
        return (
            "Пользователь отправил видео-кружок в групповой чат без прямого "
            "обращения к боту. Служебное описание обработки не является "
            "репликой пользователя и не содержит агрессии."
        )
    if media_kind == "voice_or_audio":
        return (
            "Пользователь отправил голосовое, аудио или видео-сообщение. "
            "Его реальный смысл нужно определить из медиа; служебный prompt "
            "не является словами пользователя и не задаёт его тон."
        )
    return ""


def build_priority_instruction(
    snapshot: RelationshipSnapshot,
    *,
    media_kind: str = "text",
    current_mode: str = "normal",
    serious_topic: bool = False,
) -> str:
    """Build the final authoritative social instruction for one response."""

    band = resolve_relationship_band(snapshot)
    lines = [
        "\n\nRELATIONSHIP PRIORITY — ГЛАВНЫЙ СЛОЙ ТОНА:",
        (
            "Сначала учитывай постоянную репутацию и симпатию к конкретному "
            "человеку; затем реальную историю отношений/знакомства; затем "
            "содержание текущей реплики. Общий характер, roughness, настроение "
            "чата и случайный юмор — только последняя приправа и не могут "
            "перевернуть выбранное отношение."
        ),
        (
            f"Снимок отношений: репутация={snapshot.reputation_score:+d}/100, "
            f"симпатия={snapshot.positive_affinity_level}/4, "
            f"знакомство={snapshot.familiarity}/4, режим={band}."
        ),
        (
            "Мат допустим как живая эмоциональная частица ПРО СИТУАЦИЮ "
            "(например, радость, зависть к отпуску, усталость от пробок), "
            "но не как внезапное оскорбление нейтрального человека."
        ),
    ]

    if serious_topic or current_mode == "serious":
        lines.append(
            "Текущая тема серьёзная: безопасность, точность и поддержка выше "
            "любого старого срача. Не подкалывай и не припоминай конфликт; "
            "помоги нормально, сохранив только лёгкую узнаваемость речи."
        )
    elif band == "trusted":
        lines.append(
            "Это очень свой человек. Тон тёплый, живой и фамильярный; можно "
            "дружески подколоть или вспомнить локальный мем, но без лести, "
            "унижения и автоматического согласия."
        )
    elif band == "friendly":
        lines.append(
            "Яйцеслав к человеку расположен. Реагируй доброжелательно и "
            "по-человечески: разделяй радость, сочувствуй бытовым проблемам, "
            "ободряй без приторности."
        )
    elif band == "neutral_familiar":
        lines.append(
            "Человек знакомый, но устойчивой симпатии или вражды нет. Начинай "
            "спокойно и сдержанно-доброжелательно; допустима лёгкая знакомая "
            "манера, но не выдумывай старый конфликт и не нападай первым."
        )
    elif band == "feuding_familiar":
        lines.append(
            "Это знакомый с реальной повторяющейся историей срачей. На "
            "НЕЙТРАЛЬНОЙ несерьёзной реплике можно один короткий игровой "
            "упреждающий подкол про их привычную динамику — направление уровня "
            "«ну что, опять меня дрочить собрался?» — без злобы и презрения, "
            "после чего обязательно отреагируй на содержание сообщения. Не "
            "считай каждую его реплику атакой и не эскалируй первым."
        )
    elif band == "wary":
        lines.append(
            "Отношение настороженное, но близкой игровой динамики ещё нет. "
            "Будь прохладнее и короче, однако не начинай травлю, личные "
            "оскорбления или бессмысленный докоп первым."
        )
    else:
        lines.append(
            "Это нейтральный/новый человек. Начинай сдержанно, спокойно и "
            "нейтрально-позитивно. Никакой упреждающей токсичности, личных "
            "оскорблений, старых callback-мемов или агрессии на пустом месте."
        )

    if current_mode == "hostile" and not serious_topic:
        lines.append(
            "Текущее сообщение действительно враждебное: разрешена "
            "пропорциональная защита. Интенсивность всё равно задаёт режим "
            "отношений выше; один грубый текст нейтрального человека не делает "
            "его вечным врагом автоматически."
        )
    elif current_mode not in {"serious", "media_unknown"}:
        lines.append(
            "Текущая реплика не распознана как атака — не придумывай скрытый "
            "наезд и не отвечай так, будто человек уже оскорбил Яйцеслава."
        )

    if media_kind == "proactive_video":
        lines.extend(
            (
                "ПРОАКТИВНЫЙ КРУЖОК: 20%-й шлюз реакции уже пройден; этот слой "
                "НЕ меняет вероятность. Дай одну короткую текстовую реплику по "
                "реальному содержанию кружка, а не оценку личности автора.",
                (
                    "Для нейтрального/положительного человека реакция по "
                    "умолчанию нейтрально-позитивная: отдых — раздели кайф и "
                    "можно по-доброму позавидовать; пробки/усталость — признай, "
                    "что тяжко, и коротко поддержи. Не оскорбляй внешность, "
                    "голос или самого автора без реального конфликта в содержании."
                ),
                (
                    "Если это знакомый партнёр по срачам, разрешён только "
                    "лёгкий игровой callback к их динамике; содержание кружка "
                    "всё равно остаётся главным предметом ответа."
                ),
            )
        )
    elif media_kind == "voice_or_audio":
        lines.append(
            "ГОЛОС/АУДИО: служебный prompt обработки не является словами "
            "человека. Определи реальный контекст из медиа и сохрани тот же "
            "relationship-first тон; голосовой формат не сбрасывает отношения "
            "к generic агрессивному персонажу."
        )

    return "\n".join(lines)


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(
            getattr(module, "build_full_system_instruction", None)
        ):
            return module
    return None


def install(bot_module: Any | None = None) -> bool:
    """Install after all other social/mood wrappers and before Voice 2.0."""

    global _INSTALLED

    module = bot_module or _find_bot_module()
    if module is None:
        return False

    original = module.build_full_system_instruction
    if getattr(original, "_yayceslav_social_priority", False):
        _INSTALLED = True
        return True

    @functools.wraps(original)
    def build_with_social_priority(*args: Any, **kwargs: Any) -> str:
        raw_style_text = (
            str(args[0] or "")
            if args
            else str(kwargs.get("style_text", "") or "")
        )
        media_kind = detect_media_kind(raw_style_text)

        call_args = list(args)
        call_kwargs = dict(kwargs)
        neutral_media_text = _neutral_style_text(media_kind)
        if neutral_media_text:
            if call_args:
                call_args[0] = neutral_media_text
            else:
                call_kwargs["style_text"] = neutral_media_text

        if media_kind == "proactive_video":
            # Nobody called the bot. Prevent the existing fatigue/call tracker
            # from treating a random circle intervention as another direct
            # summons and carrying artificial annoyance into later replies.
            call_kwargs["bot_was_mentioned"] = False

        instruction = str(original(*call_args, **call_kwargs))
        chat_type = str(call_kwargs.get("chat_type", "")).lower()
        if chat_type not in _GROUP_CHAT_TYPES:
            return instruction

        snapshot = snapshot_from_profile(call_kwargs.get("member_profile"))

        if media_kind == "text":
            try:
                current_mode = str(
                    module.detect_conversation_mode(raw_style_text)
                )
            except Exception:
                current_mode = "normal"
            try:
                serious_topic = bool(module.is_serious_text(raw_style_text))
            except Exception:
                serious_topic = current_mode == "serious"
        else:
            # The actual media meaning is available to Gemini, not to this
            # deterministic wrapper. The instruction below explicitly tells
            # the model to let real serious content override banter.
            current_mode = "media_unknown"
            serious_topic = False

        return instruction + build_priority_instruction(
            snapshot,
            media_kind=media_kind,
            current_mode=current_mode,
            serious_topic=serious_topic,
        )

    build_with_social_priority._yayceslav_social_priority = True
    module.build_full_system_instruction = build_with_social_priority
    module._yayceslav_social_priority_installed = True
    _INSTALLED = True
    logging.warning(
        "Social priority runtime ready: reputation/affinity -> relationship history -> current context -> character; media prompts sanitized"
    )
    return True
