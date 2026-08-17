"""Telegram command menus shown in different chat scopes.

This controls only what Telegram displays in the slash-command menu. Existing
CommandHandlers stay registered and can still be invoked manually.
"""

from __future__ import annotations

from typing import Final


# Exactly the compact group menu approved by the user.
GROUP_COMMANDS: Final[tuple[tuple[str, str], ...]] = (
    ("stickers", "Стикеры Яйцеслава"),
    ("roast", "Прожарить реплику или участника"),
    ("wisdom", "Мудрость Яйцеслава"),
    ("nickname", "Задать обращение к себе"),
    ("nickname_off", "Убрать своё обращение"),
    ("whoami", "Как Яйцеслав тебя видит"),
    ("title", "Выдать шуточный титул"),
    ("title_status", "Титул дня"),
    ("judge", "Вынести вердикт"),
    ("argument", "Разобрать аргумент"),
    ("debate", "Разобрать обе стороны спора"),
    ("leaderboard", "Таблица активности"),
    ("awards", "Награды недели"),
    ("chat_native_status", "Чему Яйцеслав научился у чата"),
)

# Private chat should be useful, not a dump of group entertainment commands.
# Hidden commands still work if typed explicitly.
PRIVATE_COMMANDS: Final[tuple[tuple[str, str], ...]] = (
    ("start", "Запустить Яйцеслава"),
    ("help", "Краткая помощь"),
    ("settings", "Личные настройки"),
    ("voice_on", "Всегда отвечать голосом"),
    ("voice_off", "Отвечать текстом"),
    ("search", "Поиск в интернете"),
    ("profile", "Мой профиль"),
    ("nickname", "Задать обращение к себе"),
    ("nickname_off", "Убрать своё обращение"),
    ("whoami", "Как Яйцеслав тебя видит"),
    ("remember_me", "Запомнить факт обо мне"),
    ("forget_me", "Удалить мой профиль"),
    ("forget", "Стереть краткую память диалога"),
    ("stickers", "Стикеры Яйцеслава"),
)

# Owner gets the complete operational menu in the owner's private chat.
OWNER_COMMANDS: Final[tuple[tuple[str, str], ...]] = (
    ("start", "Запуск"),
    ("help", "Помощь"),
    ("settings", "Личные настройки"),
    ("voice_on", "Всегда отвечать голосом"),
    ("voice_off", "Отвечать текстом"),
    ("search", "Поиск в интернете"),
    ("roast", "Прожарить реплику или участника"),
    ("wisdom", "Мудрость Яйцеслава"),
    ("mood", "Настроение"),
    ("profile", "Свой профиль"),
    ("nickname", "Задать обращение"),
    ("nickname_off", "Убрать обращение"),
    ("whoami", "Как Яйцеслав видит пользователя"),
    ("remember_me", "Запомнить факт"),
    ("forget_me", "Удалить свой профиль"),
    ("forget", "Стереть краткую память"),
    ("title", "Выдать шуточный титул"),
    ("title_status", "Титул дня"),
    ("prophecy", "Пророчество"),
    ("judge", "Вынести вердикт"),
    ("argument", "Разобрать аргумент"),
    ("debate", "Разобрать обе стороны"),
    ("explain_like_skoof", "Объяснить как скуф"),
    ("explain_like_rus", "Объяснить как древний рус"),
    ("meme", "Мемная подпись"),
    ("recap", "Пересказ недавнего чата"),
    ("fact_or_bayan", "Факт или баян"),
    ("anti_advice", "Плохой совет и нормальный"),
    ("translate_yayceslav", "Перевод с канцелярского"),
    ("duel", "Вызвать на дуэль"),
    ("story", "Продолжить историю чата"),
    ("week", "Отчёт группы за неделю"),
    ("week_me", "Моя статистика за неделю"),
    ("leaderboard", "Таблица активности"),
    ("awards", "Награды недели"),
    ("hard_on", "Включить hard-mode"),
    ("hard_off", "Выключить hard-mode"),
    ("hard_status", "Состояние hard-mode"),
    ("hard_level", "Уровень hard-mode"),
    ("hard_stats", "Статистика hard-mode"),
    ("people", "Известные участники"),
    ("set_archetype", "Задать архетип участнику"),
    ("week_auto_on", "Включить автоотчёт"),
    ("week_auto_off", "Выключить автоотчёт"),
    ("week_auto_status", "Статус автоотчёта"),
    ("week_time", "Время автоотчёта"),
    ("chat_native_status", "Что бот выучил у чата"),
    ("stickers", "Официальный стикерпак"),
    ("stats", "Общая статистика бота"),
    ("geminiversion", "Модель и версия Gemini"),
)


def command_names(commands: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    return tuple(command for command, _description in commands)


def validate_menus() -> None:
    for menu_name, commands in (
        ("group", GROUP_COMMANDS),
        ("private", PRIVATE_COMMANDS),
        ("owner", OWNER_COMMANDS),
    ):
        names = command_names(commands)
        if len(names) != len(set(names)):
            raise RuntimeError(f"Duplicate commands in {menu_name} menu")
        if len(commands) > 100:
            raise RuntimeError(f"Telegram command limit exceeded in {menu_name} menu")
        for command, description in commands:
            if not (1 <= len(command) <= 32):
                raise RuntimeError(f"Invalid command length: {command}")
            if not (1 <= len(description) <= 256):
                raise RuntimeError(f"Invalid description for /{command}")


validate_menus()
