import asyncio

from telegram.ext import Application

import command_menu
import sticker_runtime


def test_application_post_init_is_mutable_in_pinned_ptb_version():
    application = Application.builder().token("123456:TESTTOKEN").build()

    async def callback(app):
        return None

    application.post_init = callback
    assert application.post_init is callback


def test_sticker_runtime_has_no_polling_hook():
    assert not hasattr(sticker_runtime, "install_runtime_hooks")


def test_prepare_runtime_works_on_real_slotted_application_and_is_idempotent():
    application = Application.builder().token("123456:TESTTOKEN").build()
    app_id = id(application)
    sticker_runtime._PREPARED_APPLICATION_IDS.discard(app_id)
    sticker_runtime._MENU_WRAPPED_APPLICATION_IDS.discard(app_id)

    before = sum(len(group_handlers) for group_handlers in application.handlers.values())
    sticker_runtime.prepare_application_runtime(application)
    after_first = sum(len(group_handlers) for group_handlers in application.handlers.values())
    sticker_runtime.prepare_application_runtime(application)
    after_second = sum(len(group_handlers) for group_handlers in application.handlers.values())

    assert after_first == before + 5
    assert after_second == after_first
    assert app_id in sticker_runtime._PREPARED_APPLICATION_IDS
    assert app_id in sticker_runtime._MENU_WRAPPED_APPLICATION_IDS
    # Regression for Railway crash: no custom instance attrs are ever assigned.
    assert not hasattr(application, "_yayceslav_sticker_handlers_added")
    assert not hasattr(application, "_yayceslav_command_menu_startup_added")


def test_known_groups_use_shared_connection_factory(monkeypatch):
    calls = []

    class Result:
        def fetchall(self):
            return [(-1001,), (-1002,)]

    class Connection:
        def __enter__(self):
            calls.append("enter")
            return self

        def __exit__(self, exc_type, exc, tb):
            calls.append("exit")

        def execute(self, sql):
            calls.append(sql)
            return Result()

    def factory():
        calls.append("factory")
        return Connection()

    monkeypatch.setattr(
        sticker_runtime,
        "_shared_db_connection_factory",
        lambda: factory,
    )

    assert sticker_runtime._known_group_chat_ids() == (-1001, -1002)
    assert calls[0] == "factory"
    assert "SELECT chat_id FROM chats" in calls[2]
    assert calls[-1] == "exit"


def test_known_groups_fail_safe_when_shared_factory_is_not_ready(monkeypatch):
    monkeypatch.setattr(
        sticker_runtime,
        "_shared_db_connection_factory",
        lambda: None,
    )
    assert sticker_runtime._known_group_chat_ids() == ()


class FakeBot:
    def __init__(self):
        self.set_calls = []
        self.delete_calls = []

    async def set_my_commands(self, commands, *, scope):
        self.set_calls.append(
            (
                tuple(commands),
                type(scope).__name__,
                getattr(scope, "chat_id", None),
                getattr(scope, "user_id", None),
            )
        )
        return True

    async def delete_my_commands(self, *, scope):
        self.delete_calls.append(type(scope).__name__)
        return True


def test_scoped_command_installer_publishes_group_private_and_owner(monkeypatch):
    fake = FakeBot()
    monkeypatch.setenv("BOT_OWNER_ID", "747123682")
    monkeypatch.setattr(sticker_runtime, "_known_group_chat_ids", lambda: ())
    sticker_runtime._OWNER_GROUP_MENU_INSTALLED.clear()

    asyncio.run(sticker_runtime.install_scoped_command_menus(fake))

    by_scope = {
        scope: commands
        for commands, scope, _chat_id, _user_id in fake.set_calls
    }
    assert by_scope["BotCommandScopeAllGroupChats"] == command_menu.GROUP_COMMANDS
    assert by_scope["BotCommandScopeAllPrivateChats"] == command_menu.PRIVATE_COMMANDS
    assert by_scope["BotCommandScopeDefault"] == command_menu.PRIVATE_COMMANDS

    owner_private_calls = [
        (commands, chat_id)
        for commands, scope, chat_id, _user_id in fake.set_calls
        if scope == "BotCommandScopeChat"
    ]
    assert owner_private_calls == [(command_menu.OWNER_COMMANDS, 747123682)]
    assert "BotCommandScopeAllChatAdministrators" in fake.delete_calls


def test_owner_gets_full_menu_in_group_without_exposing_it_to_other_admins(monkeypatch):
    fake = FakeBot()
    monkeypatch.setenv("BOT_OWNER_ID", "747123682")
    sticker_runtime._OWNER_GROUP_MENU_INSTALLED.clear()

    installed = asyncio.run(
        sticker_runtime.install_owner_group_menu(fake, -1001234567890)
    )
    assert installed is True

    member_calls = [
        (commands, chat_id, user_id)
        for commands, scope, chat_id, user_id in fake.set_calls
        if scope == "BotCommandScopeChatMember"
    ]
    assert member_calls == [
        (command_menu.OWNER_COMMANDS, -1001234567890, 747123682)
    ]

    installed_again = asyncio.run(
        sticker_runtime.install_owner_group_menu(fake, -1001234567890)
    )
    assert installed_again is False
    assert len(member_calls) == 1
