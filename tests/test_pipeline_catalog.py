"""Factor catalog, Config, hybrid and the V1/V2 presets."""

from __future__ import annotations

import pytest

from habench.pipeline.catalog import (
    EXTEND,
    FACTORS,
    POST_FACTORS,
    V1,
    V1_EXTEND,
    V1_TO_V2,
    V2,
    Config,
    factor,
    hybrid,
)


def test_config_of_sorts_items():
    c = Config.of({"trait": "v1", "occ": "last_upsert", "map": "cm_gated"})
    assert c.items == (("map", "cm_gated"), ("occ", "last_upsert"), ("trait", "v1"))
    assert c["occ"] == "last_upsert"
    assert c.get("nope") is None
    assert c.get("nope", 3) == 3


def test_config_direct_construction_must_be_sorted_and_unique():
    with pytest.raises(ValueError):
        Config((("trait", "v1"), ("occ", "last_upsert")))
    with pytest.raises(ValueError):
        Config((("occ", "last_upsert"), ("occ", "last_upsert")))


def test_unknown_level_or_factor_raises():
    with pytest.raises(ValueError):
        Config.of({"occ": "nope"})
    with pytest.raises(ValueError):
        Config.of({"trait": "v3"})
    with pytest.raises(KeyError):
        Config.of({"zzz": 1})


@pytest.mark.parametrize("t", [0.0, 1.0, 0.123, 0.5999999, 0.575])
def test_thresholds_accept_any_float_in_unit_interval(t):
    assert Config.of({"ent_thr": t, "icd_thr": t})["ent_thr"] == t


@pytest.mark.parametrize("t", [True, False, -0.1, 1.5, "0.6"])
def test_thresholds_reject_bool_and_out_of_range(t):
    with pytest.raises(ValueError):
        Config.of({"ent_thr": t})
    with pytest.raises(ValueError):
        Config.of({"icd_thr": t})


def test_with_validates_and_diff_is_symmetric():
    c = V1.with_(occ="first_upsert")
    assert c["occ"] == "first_upsert"
    assert V1["occ"] == "last_upsert"
    assert V1.diff(c) == c.diff(V1) == frozenset({"occ"})
    assert V1.diff(V1) == frozenset()
    with pytest.raises(ValueError):
        V1.with_(occ="bogus")


def test_diff_counts_factors_present_on_one_side_only():
    assert V1.diff(V1.with_items({"patch:p": True})) == frozenset({"patch:p"})
    assert V1.with_items({"patch:p": False}).diff(V1.with_items({"patch:p": True})) == frozenset({"patch:p"})


def test_v1_v2_presets():
    assert V1.as_dict() == {
        "occ": "last_upsert", "sel": "all", "ent_thr": 0.60, "icd_thr": 0.60, "trait": "v1", "map": "cm_gated",
    }
    assert V2.as_dict() == {
        "occ": "per_entity_any", "sel": "top1", "ent_thr": 0.70, "icd_thr": 0.30, "trait": "v2",
        "map": "who_exact_fb",
    }
    assert V1.diff(V2) == frozenset(POST_FACTORS) == frozenset({"occ", "sel", "ent_thr", "icd_thr", "trait", "map"})
    assert V1_TO_V2 == (V1, V2)
    assert V1.diff(V1_EXTEND) == frozenset({"map"})
    assert V1_EXTEND["map"] == "cm_ungated"
    assert EXTEND == (V1, V1_EXTEND)


def test_hybrid_sets_only_S_to_x1_levels():
    h = hybrid(V1, V2, frozenset({"ent_thr", "trait"}))
    assert h["ent_thr"] == 0.70
    assert h["trait"] == "v2"
    for name in ("occ", "sel", "icd_thr", "map"):
        assert h[name] == V1[name]


def test_hybrid_extremes_and_rejection():
    assert hybrid(V1, V2, frozenset()) == V1
    assert hybrid(V1, V2, V1.diff(V2)) == V2
    with pytest.raises(ValueError):
        hybrid(V1, V1_EXTEND, frozenset({"occ"}))
    with pytest.raises(ValueError):
        hybrid(V1, V2, frozenset({"nope"}))


def test_patch_factor_is_binary():
    f = factor("patch:x")
    assert f.stage == "patch"
    assert f.levels == (False, True)
    assert f.available
    c = V1.with_items({"patch:x": True, "patch:y": False})
    assert c.patches_on() == frozenset({"x"})


def test_factor_lookup_and_availability():
    assert factor("occ").stage == "post"
    assert all(FACTORS[n].available for n in POST_FACTORS)
    for n in ("dup_ind", "mask_drug", "wow_rewrite", "cut10k", "translation", "acm_model"):
        assert not FACTORS[n].available
    with pytest.raises(KeyError):
        factor("unknown")
