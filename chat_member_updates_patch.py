from __future__ import annotations

from telegram.constants import UpdateType
from telegram.ext import Application


_INSTALLED = False
_ORIGINAL_RUN_POLLING = None


def install_runtime_hook() -> None:
    global _INSTALLED, _ORIGINAL_RUN_POLLING
    if _INSTALLED:
        return

    _ORIGINAL_RUN_POLLING = Application.run_polling

    def run_polling_with_chat_member_updates(self, *args, **kwargs):
        allowed = kwargs.get("allowed_updates")
        if allowed is not None:
            allowed_list = list(allowed)
            if UpdateType.CHAT_MEMBER not in allowed_list:
                allowed_list.append(UpdateType.CHAT_MEMBER)
            kwargs["allowed_updates"] = allowed_list
        return _ORIGINAL_RUN_POLLING(self, *args, **kwargs)

    Application.run_polling = run_polling_with_chat_member_updates
    _INSTALLED = True


install_runtime_hook()
