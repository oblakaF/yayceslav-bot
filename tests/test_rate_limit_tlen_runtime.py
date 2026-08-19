import asyncio
import sys
from types import SimpleNamespace

import rate_limit_tlen_runtime


def test_rate_limit_tlen_wraps_final_limiter_and_keeps_false(monkeypatch):
    calls = []

    async def limiter(update, bucket):
        calls.append(("limit", bucket))
        return False

    fake_bot_module = SimpleNamespace(enforce_rate_limit=limiter)
    monkeypatch.setitem(sys.modules, "bot", fake_bot_module)
    monkeypatch.setattr(rate_limit_tlen_runtime, "_INSTALLED", False)

    class FakeMessage:
        async def reply_sticker(self, *, sticker):
            calls.append(("sticker", sticker))

        def get_bot(self):
            return object()

    fake_message = FakeMessage()
    fake_update = SimpleNamespace(
        effective_message=fake_message,
        effective_chat=SimpleNamespace(id=-1001),
        effective_user=SimpleNamespace(id=77),
        get_bot=lambda: object(),
    )

    import sticker_runtime

    monkeypatch.setattr(sticker_runtime, "sticker_slot_allowed", lambda *args: True)

    async def ids(_bot):
        return {"vse_tlen": "FILE-ID"}

    monkeypatch.setattr(sticker_runtime, "ensure_sticker_ids", ids)
    monkeypatch.setattr(
        sticker_runtime,
        "_record_sticker_slot",
        lambda chat_id, user_id, now: calls.append(("record", chat_id, user_id)),
    )

    assert rate_limit_tlen_runtime.install() is True
    result = asyncio.run(fake_bot_module.enforce_rate_limit(fake_update, "general"))

    assert result is False
    assert ("limit", "general") in calls
    assert ("sticker", "FILE-ID") in calls
    assert ("record", -1001, 77) in calls


def test_allowed_request_does_not_send_tlen(monkeypatch):
    calls = []

    async def limiter(update, bucket):
        calls.append(("limit", bucket))
        return True

    fake_bot_module = SimpleNamespace(enforce_rate_limit=limiter)
    monkeypatch.setitem(sys.modules, "bot", fake_bot_module)
    monkeypatch.setattr(rate_limit_tlen_runtime, "_INSTALLED", False)

    assert rate_limit_tlen_runtime.install() is True
    update = SimpleNamespace(
        effective_message=SimpleNamespace(),
        effective_chat=SimpleNamespace(id=1),
        effective_user=SimpleNamespace(id=2),
    )
    assert asyncio.run(fake_bot_module.enforce_rate_limit(update, "general")) is True
    assert calls == [("limit", "general")]
