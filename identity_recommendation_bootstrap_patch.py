"""Register identity-derived recommendation verticals without a polling wrapper."""

from __future__ import annotations

import functools

import book_recommendation_runtime
import natural_router_runtime


_INSTALLED = False


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    original = natural_router_runtime.prepare_application_runtime
    if getattr(original, "_yayceslav_identity_recommendation_hook", False):
        _INSTALLED = True
        return True

    @functools.wraps(original)
    def prepare_then_identity_recommendations(application):
        original(application)
        book_recommendation_runtime.prepare_application_runtime(application)

    prepare_then_identity_recommendations._yayceslav_identity_recommendation_hook = True
    natural_router_runtime.prepare_application_runtime = prepare_then_identity_recommendations
    _INSTALLED = True
    return True


install()
