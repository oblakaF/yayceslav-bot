import random

import member_profile_runtime
import title_pools
import unified_daily_title_runtime as runtime


def test_classify_member_by_week_activity():
    assert runtime.classify_member(total_messages=0, week_messages=0) == "never_spoke"
    assert runtime.classify_member(total_messages=50, week_messages=0) == "silent_week"
    assert runtime.classify_member(total_messages=50, week_messages=1) == "active"


def test_candidate_is_random_across_all_members_and_yesterday_winner_is_excluded():
    candidates = [
        {"user_id": 1},
        {"user_id": 2},
        {"user_id": 3},
    ]
    for seed in range(20):
        chosen = runtime.choose_candidate(candidates, previous_user_id=2, rng=random.Random(seed))
        assert chosen is not None
        assert chosen["user_id"] in {1, 3}


def test_only_yesterday_winner_means_no_repeat_today():
    assert runtime.choose_candidate([{"user_id": 5}], previous_user_id=5) is None


def test_silent_member_gets_only_silent_pool():
    candidate = {"previous_title": None}
    title = runtime._pick_title_for(candidate, "silent_week", rng=random.Random(2))
    assert title in member_profile_runtime.SILENT_WEEK_TITLES


def test_never_spoke_member_gets_never_pool():
    candidate = {"previous_title": None}
    title = runtime._pick_title_for(candidate, "never_spoke", rng=random.Random(2))
    assert title in member_profile_runtime.SILENT_NEVER_TITLES


def test_active_member_gets_normal_title_pool():
    candidate = {"previous_title": None}
    title = runtime._pick_title_for(candidate, "active", rng=random.Random(2))
    assert title in title_pools.ALL_TITLES
