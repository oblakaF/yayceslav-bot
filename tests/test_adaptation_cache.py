from telegram.ext import Application

import adaptation_cache
import runtime_bootstrap


def test_cache_reuses_value_until_invalidated():
    adaptation_cache.clear()
    calls = []

    def loader():
        calls.append(1)
        return {"value": len(calls)}

    first = adaptation_cache.get_or_load(
        "feedback", -100, loader, ttl_seconds=60, now=lambda: 10.0
    )
    second = adaptation_cache.get_or_load(
        "feedback", -100, loader, ttl_seconds=60, now=lambda: 20.0
    )

    assert first == second == {"value": 1}
    assert len(calls) == 1

    adaptation_cache.invalidate("feedback", -100)
    third = adaptation_cache.get_or_load(
        "feedback", -100, loader, ttl_seconds=60, now=lambda: 21.0
    )
    assert third == {"value": 2}
    assert len(calls) == 2


def test_cache_expires_and_isolated_by_chat():
    adaptation_cache.clear()
    calls = []

    def loader():
        calls.append(1)
        return len(calls)

    assert adaptation_cache.get_or_load(
        "native", -1, loader, ttl_seconds=5, now=lambda: 0.0
    ) == 1
    assert adaptation_cache.get_or_load(
        "native", -2, loader, ttl_seconds=5, now=lambda: 1.0
    ) == 2
    assert adaptation_cache.get_or_load(
        "native", -1, loader, ttl_seconds=5, now=lambda: 6.0
    ) == 3


def test_runtime_bootstrap_documents_critical_wrapper_order():
    order = runtime_bootstrap.RUNTIME_LOAD_ORDER

    # These are semantic ordering constraints of the current wrapper chain,
    # not source-text assertions. If the architecture is later consolidated,
    # this contract can be removed together with the wrappers.
    assert order.index("monthly_social_runtime") < order.index("unified_daily_title_runtime")
    assert order.index("unified_daily_title_runtime") < order.index("whoami_profile_v4_runtime")
    assert order.index("whoami_profile_v3_runtime") < order.index("monthly_memory_scope_patch")
    assert order.index("monthly_memory_scope_patch") < order.index("whoami_profile_v4_runtime")
    assert order.index("daily_content_runtime") < order.index("daily_content_source_patch")


def test_consolidated_monthly_patches_do_not_reenter_bootstrap():
    order = runtime_bootstrap.RUNTIME_LOAD_ORDER
    assert "monthly_report_timing_patch" not in order
    assert "monthly_theme_quality_patch" not in order


def test_schema_preflight_is_installed_as_central_bootstrap_hook():
    assert getattr(Application, "_yayceslav_schema_preflight_installed", False) is True


def test_schema_preflight_delegates_to_versioned_migrations(monkeypatch):
    fake_bot_module = object()
    calls = []
    monkeypatch.setattr(runtime_bootstrap, "_find_bot_module", lambda: fake_bot_module)
    monkeypatch.setattr(
        runtime_bootstrap.schema_migrations,
        "run_pending",
        lambda bot_module: calls.append(bot_module) or (1,),
    )

    assert runtime_bootstrap.run_schema_preflight() == (1,)
    assert calls == [fake_bot_module]
