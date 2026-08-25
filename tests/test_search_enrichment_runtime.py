from search_enrichment_runtime import rank_results, result_quality_score


def test_low_value_social_result_is_ranked_below_news_source():
    results = [
        {
            "title": "Видео",
            "url": "https://www.tiktok.com/discover/example",
            "snippet": "Актуальный ролик и обсуждение чего-то в сети.",
        },
        {
            "title": "Reuters report",
            "url": "https://www.reuters.com/world/example",
            "snippet": "A sufficiently descriptive report snippet with current factual context and details.",
        },
    ]

    ranked = rank_results(results)
    assert ranked[0]["url"].startswith("https://www.reuters.com/")
    assert result_quality_score(ranked[0]) > result_quality_score(ranked[1])


def test_sort_is_stable_for_equal_quality_results():
    results = [
        {"title": "A", "url": "https://example.com/a", "snippet": "short"},
        {"title": "B", "url": "https://example.net/b", "snippet": "short"},
    ]
    assert [item["title"] for item in rank_results(results)] == ["A", "B"]
