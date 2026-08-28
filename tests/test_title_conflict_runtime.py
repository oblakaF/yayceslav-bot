import random

import title_conflict_runtime as runtime
import title_pools


def test_unresolved_self_feud_forces_title_punishment():
    assert runtime.should_punish_self_title(
        requester_id=10,
        target_id=10,
        active_insults_today=1,
        penance_pending=False,
    )
    assert runtime.should_punish_self_title(
        requester_id=10,
        target_id=10,
        active_insults_today=0,
        penance_pending=True,
    )


def test_clean_self_title_is_not_punished():
    assert not runtime.should_punish_self_title(
        requester_id=10,
        target_id=10,
        active_insults_today=0,
        penance_pending=False,
    )


def test_requester_feud_does_not_punish_replied_target():
    assert not runtime.should_punish_self_title(
        requester_id=10,
        target_id=20,
        active_insults_today=4,
        penance_pending=True,
    )


def test_forced_title_comes_from_negative_pool():
    negative_titles = {
        title
        for pool_name in title_pools.pools_for_tier("negative")
        for title in title_pools.TITLE_POOLS[pool_name]
    }
    title = runtime.choose_hostile_title(None, rng=random.Random(7))
    assert title in negative_titles


def test_rage_title_reply_is_not_wholesome():
    reply = runtime.format_hostile_title_reply(
        "Камень-Дрочер",
        "Почётный долбоёб района",
        rage=True,
    )
    assert "срался" in reply
    assert "Почётный долбоёб района" in reply
    assert "не ной" in reply


def test_non_rage_hostile_title_still_refuses_positive_reward():
    reply = runtime.format_hostile_title_reply(
        "Камень-Дрочер",
        "Магистр ебанистики",
        rage=False,
    )
    assert "добрый титул ты не заслужил" in reply
    assert "Магистр ебанистики" in reply
