import title_pools
import title_reroll_runtime


class FirstChoiceRng:
    def choice(self, seq):
        return list(seq)[0]


def test_reroll_request_detects_colloquial_change_requests():
    assert title_reroll_runtime.is_title_reroll_request("дай другой титул")
    assert title_reroll_runtime.is_title_reroll_request("титул хуйня, меняй")
    assert title_reroll_runtime.is_title_reroll_request(
        "меняй",
        replied_to_daily_title=True,
    )


def test_restore_old_title_request_is_detected():
    assert title_reroll_runtime.is_title_reroll_request("старый титул верни")
    assert title_reroll_runtime._RESTORE_OLD_RE.search("верни прошлый")


def test_generated_title_sanitizer_rejects_recent_duplicate():
    excluded = {"Владелец Золотого Тюбика"}
    assert title_reroll_runtime._sanitize_generated_title(
        "«Владелец Золотого Тюбика»",
        excluded,
    ) is None
    assert title_reroll_runtime._sanitize_generated_title(
        "Министр Титульных Жалоб",
        excluded,
    ) == "Министр Титульных Жалоб"


def test_pool_picker_excludes_recent_chat_wide_titles():
    title = title_pools.pick_title(
        None,
        excluded_titles={
            "Почётный эксперт чата",
            "Умничка",
            "Хороший мальчик",
        },
        rng=FirstChoiceRng(),
    )
    assert title not in {
        "Почётный эксперт чата",
        "Умничка",
        "Хороший мальчик",
    }
