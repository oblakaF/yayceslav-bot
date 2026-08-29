"""Runtime integration for the intelligent roast planner.

Installed after fight_routing_v3 so it sees the final current-turn routing and
only enriches the existing RAGE system prompt.  No extra model/API call.
"""

from __future__ import annotations

import functools
import logging
import sys
from typing import Any

import conflict_fsm_runtime
import roast_engine


_INSTALLED = False


def _find_bot_module() -> Any | None:
    for name in ("__main__", "bot"):
        module = sys.modules.get(name)
        if module is not None and callable(getattr(module, "build_full_system_instruction", None)):
            return module
    return None


def _call_argument(args, kwargs, *, name: str, position: int, default=None):
    if name in kwargs:
        return kwargs[name]
    if len(args) > position:
        return args[position]
    return default


def install(bot_module: Any | None = None) -> bool:
    global _INSTALLED
    module = bot_module or _find_bot_module()
    if module is None:
        return False
    if _INSTALLED:
        return True

    original = module.build_full_system_instruction
    if getattr(original, "_yayceslav_roast_engine_v1", False):
        _INSTALLED = True
        return True

    @functools.wraps(original)
    def build_with_roast_plan(*args: Any, **kwargs: Any) -> str:
        instruction = str(original(*args, **kwargs))

        chat_type = str(_call_argument(args, kwargs, name="chat_type", position=4, default="") or "").lower()
        if chat_type not in ("group", "supergroup"):
            return instruction

        chat_id = _call_argument(args, kwargs, name="chat_id", position=2, default=None)
        user_id = _call_argument(args, kwargs, name="user_id", position=3, default=None)
        style_text = _call_argument(args, kwargs, name="style_text", position=0, default="")
        if chat_id is None or user_id is None:
            return instruction

        try:
            phase = conflict_fsm_runtime.phase(int(chat_id), int(user_id))
        except Exception:
            return instruction
        if phase is not conflict_fsm_runtime.ConflictPhase.RAGE:
            return instruction

        try:
            import fight_routing_v3
            current_text = fight_routing_v3.current_turn_text(style_text)
        except Exception:
            current_text = str(style_text or "")
        if not current_text:
            return instruction

        plan = roast_engine.observe_and_plan(int(chat_id), int(user_id), current_text)
        return instruction + roast_engine.prompt_for_plan(plan)

    build_with_roast_plan._yayceslav_roast_engine_v1 = True
    module.build_full_system_instruction = build_with_roast_plan
    _INSTALLED = True
    logging.warning(
        "Roast engine v1 ready: RAGE weak-point planner, angle rotation, callbacks, structured profanity palette"
    )
    return True
