import sticker_semantics_aug19


def test_aug19_catalog_accepts_with_or_without_duplicate_pereigral():
    sticker_semantics_aug19.install_catalog_semantics()

    order_47 = sticker_semantics_aug19._active_order_for_count(47)
    order_48 = sticker_semantics_aug19._active_order_for_count(48)

    assert len(order_47) == 47
    assert len(order_48) == 48
    assert "pereigral_i_unichtozhil_new" not in order_47
    assert "pereigral_i_unichtozhil_new" in order_48

    # The optional duplicate is the only positional difference, so later
    # stickers keep their correct semantic key in either live-pack layout.
    assert order_47[-4:] == (
        "nu_i_suka_zhe_ty",
        "a_zachem_eto",
        "fa_watafa",
        "delo_pahnet_ostrovom",
    )
    assert order_48[-4:] == order_47[-4:]
