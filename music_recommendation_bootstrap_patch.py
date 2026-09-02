"""Register music recommendations without adding another polling wrapper."""

from __future__ import annotations

import functools

import music_recommendation_runtime
import natural_router_runtime


_INSTALLED = False


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    original = natural_router_runtime.prepare_application_runtime
    if getattr(original, "_yayceslav_music_recommendation_hook", False):
        _INSTALLED = True
        return True

    @functools.wraps(original)
    def prepare_then_recommendations(application):
        original(application)
        music_recommendation_runtime.prepare_application_runtime(application)

    prepare_then_recommendations._yayceslav_music_recommendation_hook = True
    natural_router_runtime.prepare_application_runtime = prepare_then_recommendations
    _INSTALLED = True
    return True


install()
