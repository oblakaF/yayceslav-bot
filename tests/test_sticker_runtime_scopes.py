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


def test_sticker_runtime_patch_is_installed_once():
    assert getattr(Application, "_yayceslav_sticker_patch_installed", False) is True


class FakeBot:
    def __init__(self):
        self.set_calls = []
        self.delete_calls = []

    async def set_my_commands(self, commands, *, scope):
        self.set_calls.append((tuple(commands), type(scope).__name__, getattr(scope, "chat_id", None)))
        return True

    async def delete_my_commands(self, *, scope):
        self.delete_calls.append(type(scope).__name__)
        return True


def test_scoped_command_installer_publishes_group_private_and_owner(monkeypatch):
    fake = FakeBot()
    monkeypatch.setenv("BOT_OWNER_ID", "747123682")

    asyncio.run(sticker_runtime.install_scoped_command_menus(fake))

    by_scope = {scope: commands for commands, scope, _chat_id in fake.set_calls}
    assert by_scope["BotCommandScopeAllGroupChats"] == command_menu.GROUP_COMMANDS
    assert by_scope["BotCommandScopeAllPrivateChats"] == command_menu.PRIVATE_COMMANDS
    assert by_scope["BotCommandScopeDefault"] == command_menu.PRIVATE_COMMANDS

    owner_calls = [
        (commands, chat_id)
        for commands, scope, chat_id in fake.set_calls
        if scope == "BotCommandScopeChat"
    ]
    assert owner_calls == [(command_menu.OWNER_COMMANDS, 747123682)]
    assert "BotCommandScopeAllChatAdministrators" in fake.delete_calls
