import adaptation_cache


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
