from __future__ import annotations

import pytest

from habench.historical import contrast
from habench.historical.contrast import minimal_family, summarize_tables


def table(bits: dict[int, int], n: int) -> int:
    return sum(v << s for s, v in bits.items() if s < (1 << n))


def test_protocol_7_2_example_two_minimal_sets():
    # factors: bit0 = threshold, bit1 = candidate; absent at empty, present once either changes
    t = table({0: 0, 1: 1, 2: 1, 3: 1}, 2)
    minimal, nm = minimal_family(t, 2)
    assert minimal == {1, 2}
    assert not nm


def test_third_inert_factor_is_in_no_minimal_set():
    n = 3
    bits = {s: 0 if (s & 3) == 0 else 1 for s in range(8)}
    minimal, nm = minimal_family(table(bits, n), n)
    assert minimal == {1, 2}
    stats = summarize_tables({table(bits, n): 5}, n)
    assert stats["shape_histogram"] == {"2": 5}
    assert stats["appear"] == 5 and stats["disappear"] == 0
    assert stats["non_monotone"] == 0


def test_single_factor_and_conjunction():
    assert minimal_family(table({0: 0, 1: 0, 2: 0, 3: 1}, 2), 2) == (frozenset({3}), False)
    assert minimal_family(table({0: 0, 1: 1, 2: 0, 3: 1}, 2), 2) == (frozenset({1}), False)


def test_non_monotone_family():
    # present under {a}, absent under {a, b}, present under D = {a, b, c}: {a} is sufficient, {a, b} is not
    n = 3
    bits = {0: 0, 1: 1, 2: 0, 3: 0, 4: 0, 5: 1, 6: 0, 7: 1}
    minimal, nm = minimal_family(table(bits, n), n)
    assert nm
    assert minimal == {1}  # {a} suffices; {a, c} contains it
    assert summarize_tables({table(bits, n): 2}, n)["non_monotone"] == 2


def test_disappearing_association_and_unchanged_are_split():
    n = 2
    gone = table({0: 1, 1: 0, 2: 1, 3: 0}, n)
    same = table({0: 1, 1: 1, 2: 1, 3: 1}, n)
    stats = summarize_tables({gone: 3, same: 10}, n)
    assert stats["n_changed"] == 3 and stats["disappear"] == 3 and stats["appear"] == 0
    assert stats["shape_histogram"] == {"1": 3}
    assert stats["distinct_truth_tables_changed"] == 1


def test_participation_counts_factors_in_some_minimal_set():
    n = 2
    t = table({0: 0, 1: 1, 2: 0, 3: 1}, n)
    names = contrast.factor_order()
    stats = summarize_tables({t: 4}, n)
    assert stats["participation"][names[0]] == 4
    assert stats["participation"][names[1]] == 0


def test_factor_order_is_the_six_post_factors():
    assert contrast.factor_order() == ("ent_thr", "icd_thr", "map", "occ", "sel", "trait")


@pytest.mark.parametrize("seed", range(5))
def test_family_matches_brute_force(seed):
    import random

    rng = random.Random(seed)
    n = 4
    bits = [rng.randint(0, 1) for _ in range(1 << n)]
    t = sum(b << s for s, b in enumerate(bits))
    target = bits[-1]
    suff = {s for s in range(1 << n) if bits[s] == target}
    want = {s for s in suff if not any(u in suff for u in range(s) if u & s == u and u != s)}
    assert minimal_family(t, n)[0] == want


@pytest.mark.dumps
def test_full_corpus_contrast_numbers():
    c = contrast.compute(("full_corpus",))["full_corpus"]
    assert c["n_keys_v1"] == 34_101
    assert c["appear"] == 27_405
    assert c["disappear"] == 18_284
    assert c["shape_histogram"] == {"1": 27_874, "2": 14_182, "3": 3_464, "4": 168, "5": 1}
    assert c["participation"] == {
        "sel": 23_425, "occ": 18_859, "trait": 17_561, "icd_thr": 12_784, "ent_thr": 2_287, "map": 0,
    }
    assert c["non_monotone"] == 4_555


@pytest.mark.dumps
def test_committed_results_equal_a_fresh_computation():
    import json

    from habench.historical import study_a

    fresh = json.loads(study_a.render(study_a.compute()))
    assert json.loads(study_a.OUT_PATH.read_text(encoding="utf-8")) == fresh
