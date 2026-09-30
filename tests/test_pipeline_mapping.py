"""Hierarchy lookups on a small synthetic hierarchy."""

from __future__ import annotations

import pytest

from habench.pipeline.mapping import (
    MAP_CAT3_FALLBACK,
    MAP_CAT_EXACT,
    MAP_NO_MAP,
    MAP_SUBCAT_EXACT,
    Hierarchy,
    extend_ids,
    v1_gate,
    v1_ids,
    v2_ids,
    who_map,
)

CATS = [
    {"cd_cat": "I10", "id_cat": 1, "id_group": 1},
    {"cd_cat": "E11", "id_cat": 2, "id_group": 1},
    {"cd_cat": "J45", "id_cat": 3, "id_group": 2},
    {"cd_cat": "U8", "id_cat": 4, "id_group": 3},  # short (2-char) category
    {"cd_cat": "K50", "id_cat": 5, "id_group": 2},
]
SUBS = [
    {"cd_subcat": "E110", "id_subcat": 10, "id_cat": 2},
    {"cd_subcat": "E119", "id_subcat": 11, "id_cat": 2},
    {"cd_subcat": "J450", "id_subcat": 12, "id_cat": 2},  # subcategory whose category differs from its prefix
    {"cd_subcat": "K50", "id_subcat": 13, "id_cat": 5},  # same code as a category
]
H = Hierarchy.from_rows(CATS, SUBS)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("I10", True),  # category
        ("E11.9", True),  # subcategory (dot dropped)
        ("E11.65", True),  # 3-char prefix is a category
        ("U8", True),  # short code that is a category
        ("U", False),  # too short and unknown
        ("Z99.9", False),
        ("Z99", False),
    ],
)
def test_v1_gate(code, expected):
    assert v1_gate(H, code) is expected


def test_v1_ids_prefix_then_subcategory_override():
    assert v1_ids(H, "E11.9") == (1, 2, 11)
    assert v1_ids(H, "E11.65") == (1, 2, None)
    assert v1_ids(H, "J45.9") == (2, 3, None)
    # exact subcategory overrides the category (and group) found by the prefix
    assert v1_ids(H, "J45.0") == (1, 2, 12)
    assert v1_ids(H, "Z99.9") == (None, None, None)


def test_extend_ids_independent_lookups():
    # whole-code lookups are independent; no prefix fallback when the subcategory hit
    assert extend_ids(H, "E11.9") == (None, None, 11)
    assert extend_ids(H, "I10") == (1, 1, None)
    assert extend_ids(H, "K50") == (2, 5, 13)  # both hit
    # prefix only when both whole-code lookups miss
    assert extend_ids(H, "E11.65") == (1, 2, None)
    assert extend_ids(H, "J45.9") == (2, 3, None)
    assert extend_ids(H, "Z99.9") == (None, None, None)


def test_who_map_exact_fb():
    assert who_map(H, "E11.9") == ("E119", MAP_SUBCAT_EXACT)
    assert who_map(H, "E11.65") == ("E11", MAP_CAT3_FALLBACK)
    assert who_map(H, "I10") == ("I10", MAP_CAT3_FALLBACK)  # like V2: a 3-char category is labelled fallback
    assert who_map(H, "K50") == ("K50", MAP_SUBCAT_EXACT)
    assert who_map(H, "Z99.9") == (None, MAP_NO_MAP)


def test_who_map_exact():
    assert who_map(H, "E11.9", "exact") == ("E119", MAP_SUBCAT_EXACT)
    assert who_map(H, "I10", "exact") == ("I10", MAP_CAT_EXACT)
    assert who_map(H, "E11.65", "exact") == (None, MAP_NO_MAP)
    assert who_map(H, "Z99.9", "exact") == (None, MAP_NO_MAP)


def test_who_map_cat3():
    assert who_map(H, "E11.9", "cat3") == ("E11", MAP_CAT3_FALLBACK)
    assert who_map(H, "E11.65", "cat3") == ("E11", MAP_CAT3_FALLBACK)
    assert who_map(H, "Z99.9", "cat3") == (None, MAP_NO_MAP)


def test_who_map_unknown_policy():
    with pytest.raises(ValueError):
        who_map(H, "E11.9", "nope")


def test_v2_ids():
    assert v2_ids(H, "E11.9") == (1, 2, 11)
    assert v2_ids(H, "J45.0") == (1, 2, 12)  # subcategory's category, then its group
    assert v2_ids(H, "E11.65") == (1, 2, None)
    assert v2_ids(H, "I10") == (1, 1, None)
    assert v2_ids(H, "K50") == (2, 5, 13)
    assert v2_ids(H, "Z99.9") == (None, None, None)


def test_version_is_stable_under_row_order_and_sensitive_to_content():
    h2 = Hierarchy.from_rows(list(reversed(CATS)), list(reversed(SUBS)))
    assert h2.version == H.version
    assert H.version.startswith("hier:") and len(H.version) == len("hier:") + 16
    h3 = Hierarchy.from_rows(CATS, SUBS[:-1])
    assert h3.version != H.version
    h4 = Hierarchy.from_rows([{**CATS[0], "id_group": 9}, *CATS[1:]], SUBS)
    assert h4.version != H.version
