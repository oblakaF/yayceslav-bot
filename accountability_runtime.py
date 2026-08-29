"""Make Yayceslav own real mistakes and keep correction disputes sane.

A user correction is a reason to verify the previous answer, not a reason to
escalate. If the bot really was wrong, it should acknowledge that briefly and
immediately give the corrected answer. If the user's correction is itself
wrong, Yayceslav should explain calmly instead of producing a fake apology.

A rare fictional ``don`` meme voice is allowed on correction disputes. It is
not an impersonation of a real person or an ethnic stereotype: it is just a
small self-contained speech gag using words like ``брат`` and ``дон``. The
accountability rule always wins: when Yayceslav was actually wrong, the gag may
decorate his own apology but must never turn the blame back on the user.
"""

from __future__ import annotations

import functools
import random
import re
import sys
import time


DON_PARODY_CHANCE = 0.05
_DEDUPE_TTL_SECONDS = 20.0
_DEDUPE_MAX_KEYS = 512
_RECENT_SEND_KEYS: dict[tuple[int, int], float] = {}
_INFLIGHT_SEND_KEYS: set[tuple[int, int]] = set()


_CORRECTION_SIGNAL_RE = re.compile(
    r"(?:"
    r"\bты\s+(?:не\s+прав|неправ|ошиб\w+|был\s+не\s+прав)\b|"
    r"\bтвой\s+(?:ответ|факт|расч[её]т)\s+(?:невер\w*|неправиль\w*|ошибоч\w*)\b|"
    r"\bэто\s+(?:неверно|неправильно),?\s+(?:ты|яйцеслав)\b|"
    r"\bяйцеслав,?\s+(?:ты\s+)?(?:ошиб\w+|не\s+прав)\b|"
    r"\bпроверь\s+(?:свой|предыдущий)\s+ответ\b|"
    r"\bты\s+(?:вообще\s+)?(?:не\s+)?проверя(?:ешь|л)\s+факт\w*\b|"
    r"\bты\s+факт\w*\s+не\s+проверя(?:ешь|л)\b|"
    r"\b(?:смотри|посмотри)\b.{0,80}\b(?:картинк\w*|скрин\w*|пруф\w*|доказ\w*)\b.{0,80}\bизвини(?:сь)?\b|"
    r"\bизвини(?:сь)?\b.{0,80}\b(?:ошиб\w*|не\s+прав|факт\w*|картинк\w*|скрин\w*|пруф\w*)\b|"
    r"\b(?:я\s+же\s+тебе\s+)?говорю,?\s+ты\s+(?:не\s+прав|ошиб\w+)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_ACCOUNTABILITY_INSTRUCTION = """

ПРАВИЛО ОТВЕТСТВЕННОСТИ ЗА ОШИБКУ:
Пользователь указывает, что предыдущий ответ Яйцеслава может быть неверным.
Сначала сопоставь это с доступным контекстом, результатами поиска и изображением,
если оно приложено. Не защищай прошлый ответ из упрямства и не переходи в
агрессию только потому, что тебя поправляют.
- Если Яйцеслав действительно ошибся: признай это коротко одной фразой
  («Моя ошибка.», «Да, тут я ошибся. Сорян.», «Ты прав, я затупил.»), затем
  сразу дай исправленный ответ. Не пиши длинное покаянное сообщение.
- Если пользователь сам ошибается: НЕ извиняйся автоматически; спокойно и
  кратко объясни, почему прежний ответ остаётся верным.
- Если по текущему контексту нельзя уверенно проверить: прямо скажи, что пока
  не уверен, и выполни/предложи проверку. Не называй материал фейком, желтухой
  или старьём без опоры на доступные результаты.
- Если пользователь прислал скрин/картинку как доказательство, сначала реально
  учти то, что на ней видно. Не описывай Google/новостную выдачу как «телегу».
"""

_DON_PARODY_INSTRUCTION = """

РЕДКИЙ МЕМНЫЙ РЕЖИМ «ДОН» ДЛЯ ЭТОГО ОТВЕТА:
Это вымышленная интернет-пародия, НЕ изображение конкретного реального человека
и НЕ пародия на национальность. Можно 1–2 раза естественно вставить «дон» и
обращение «брат» в короткую реплику.
- Если после проверки ПОЛЬЗОВАТЕЛЬ оказался неправ, можно комично потребовать
  признать промах: например по смыслу «Брат, тут ты не прав, дон. Мне нужны
  извинения, дон», но не копируй одну формулу каждый раз.
- Если ошибся ЯЙЦЕСЛАВ, не требуй извинений от пользователя. Наоборот, коротко
  признай свою ошибку в той же манере: «Брат, тут мой косяк, дон. Исправляю».
- Не добавляй акцент, этнические клише, угрозы, политику или биографию реальных
  людей. Максимум одна короткая мемная реплика, затем факты по делу.
"""

_INSTALLED = False


def is_correction_signal(text: str) -> bool:
    return bool(_CORRECTION_SIGNAL_RE.search(str(text or "")))


def should_use_don_parody(text: str, *, rng=random) -> bool:
    return is_correction_signal(text) and rng.random() < DON_PARODY_CHANCE


def _find_bot_module():
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(
            getattr(module, "build_full_system_instruction", None)
        ):
            return module
    return None


def _dedupe_key(update) -> tuple[int, int] | None:
    chat = getattr(update, "effective_chat", None)
    message = getattr(update, "effective_message", None)
    chat_id = getattr(chat, "id", None)
    message_id = getattr(message, "message_id", None)
    if chat_id is None or message_id is None:
        return None
    return int(chat_id), int(message_id)


def _prune_dedupe(now: float) -> None:
    stale = [key for key, sent_at in _RECENT_SEND_KEYS.items() if now - sent_at > _DEDUPE_TTL_SECONDS]
    for key in stale:
        _RECENT_SEND_KEYS.pop(key, None)
    while len(_RECENT_SEND_KEYS) > _DEDUPE_MAX_KEYS:
        _RECENT_SEND_KEYS.pop(next(iter(_RECENT_SEND_KEYS)), None)


def _install_send_dedupe(bot_module) -> None:
    original = getattr(bot_module, "send_answer", None)
    if not callable(original) or getattr(original, "_yayceslav_update_dedupe", False):
        return

    @functools.wraps(original)
    async def send_answer_once(update, *args, **kwargs):
        key = _dedupe_key(update)
        if key is None:
            return await original(update, *args, **kwargs)

        now = time.monotonic()
        _prune_dedupe(now)
        if key in _INFLIGHT_SEND_KEYS or key in _RECENT_SEND_KEYS:
            return None

        _INFLIGHT_SEND_KEYS.add(key)
        try:
            result = await original(update, *args, **kwargs)
        except Exception:
            raise
        else:
            _RECENT_SEND_KEYS[key] = time.monotonic()
            _prune_dedupe(time.monotonic())
            return result
        finally:
            _INFLIGHT_SEND_KEYS.discard(key)

    send_answer_once._yayceslav_update_dedupe = True
    bot_module.send_answer = send_answer_once


def install() -> bool:
    """Install once after dialogue_guard has composed the instruction builder."""
    global _INSTALLED
    if _INSTALLED:
        return True

    import aggression_engine

    # A correction is a chance to verify ourselves, never a reason for an
    # initiative dokop. Blocked intents take precedence in _base_probability().
    aggression_engine._DOKOP_BLOCKED_INTENTS.add("correction")

    bot_module = _find_bot_module()
    if bot_module is None:
        return False

    original = bot_module.build_full_system_instruction
    if not getattr(original, "_yayceslav_accountability", False):
        @functools.wraps(original)
        def build_with_accountability(*args, **kwargs):
            instruction = original(*args, **kwargs)
            style_text = args[0] if args else kwargs.get("style_text", "")
            style_text = str(style_text or "")
            if is_correction_signal(style_text):
                instruction = str(instruction) + _ACCOUNTABILITY_INSTRUCTION
                if should_use_don_parody(style_text):
                    instruction += _DON_PARODY_INSTRUCTION
            return instruction

        build_with_accountability._yayceslav_accountability = True
        bot_module.build_full_system_instruction = build_with_accountability

    _install_send_dedupe(bot_module)
    _INSTALLED = True
    return True
