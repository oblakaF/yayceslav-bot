import title_pools
import title_traits


def test_known_title_has_a_trait():
    assert title_traits.trait_for_title("Смотрящий за чатом") is not None
    assert "смотрящий" in title_traits.trait_for_title("Смотрящий за чатом")


def test_unknown_title_has_no_trait():
    assert title_traits.trait_for_title("Мудак Премиум") is None


def test_none_title_has_no_trait():
    assert title_traits.trait_for_title(None) is None


def test_every_traited_title_actually_exists_in_the_pools():
    assert set(title_traits.TITLE_TRAITS) <= set(title_pools.ALL_TITLES)
