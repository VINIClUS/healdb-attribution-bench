import hashlib

import pytest

from habench.data import groups as G


def _words(n, tag="w"):
    return " ".join(f"{tag}{i}" for i in range(n))


def test_normalize_pt():
    assert G.normalize_pt("  Doré   de\tCABEÇA \n") == "doré de cabeça"
    assert G.normalize_pt("A  B") == "a b"


def test_group_id_formula():
    expect = "g" + hashlib.sha256(b"3,10,42").hexdigest()[:12]
    assert G.group_id([42, 3, 10]) == expect


def test_jaccard_boundary_exact():
    # 19 shared shingles of 20 vs 19+... : sets built from words so shingle counts are controlled
    base = _words(24)  # 20 shingles
    # append one word: 21 shingles, 20 shared -> J = 20/21 (> 0.9)
    assert G.near_pairs([G.shingles(base), G.shingles(base + " x")]) == [(0, 1)]
    # exactly 0.90: A has 9 shingles, B has 10 (superset): 9/10
    a = _words(13)  # 9 shingles
    b = a + " z"  # 10 shingles, superset
    assert G.near_pairs([G.shingles(a), G.shingles(b)]) == [(0, 1)]
    # just below: 9 vs 11 shingles (superset) -> 9/11
    c = a + " z y"
    assert G.near_pairs([G.shingles(a), G.shingles(c)]) == []


def test_near_pairs_matches_bruteforce():
    import random

    rng = random.Random(1)
    vocab = [f"t{i}" for i in range(6)]
    texts = [" ".join(rng.choice(vocab) for _ in range(rng.randint(3, 30))) for _ in range(60)]
    sets = [G.shingles(t) for t in texts]
    brute = [
        (i, j)
        for i in range(len(sets))
        for j in range(i + 1, len(sets))
        if 10 * len(sets[i] & sets[j]) >= 9 * len(sets[i] | sets[j])
    ]
    assert G.near_pairs(sets) == brute


def test_short_texts_single_shingle():
    assert G.shingles("a b c") == frozenset([("a", "b", "c")])


def test_build_groups_three_relations():
    base = _words(24)
    texts = {
        1: ("Tosse  seca", "cough"),
        2: ("tosse seca", "other"),  # pt_exact with 1
        3: (base, "e3"),
        4: (base + " x", "e4"),  # pt_near with 3
        5: ("zzz", "shared en"),
        6: ("yyy", " shared en "),  # en_exact with 5
        7: ("isolated", "alone"),
        8: (_words(24, "q"), "e8"),
        9: ("m n o", "e3"),  # en_exact with 3 -> joins {3,4,9}
    }
    groups, records = G.build_groups(texts)
    by_med = {r.medication: r for r in records}
    members = sorted(g.meds for g in groups)
    assert members == [(1, 2), (3, 4, 9), (5, 6), (7,), (8,)]
    assert by_med[1].link == "pt_exact" and by_med[2].link == "pt_exact"
    assert by_med[3].link == "en_exact;pt_near" and by_med[4].link == "pt_near"
    assert by_med[9].link == "en_exact" and by_med[7].link == "singleton"
    assert by_med[5].link == "en_exact"
    assert by_med[1].group_id == G.group_id([1, 2])
    assert by_med[1].pt_sha256 == hashlib.sha256("Tosse  seca".encode()).hexdigest()


def test_summarize_reports_large_component():
    groups = [G.Group("a", tuple(range(80))), G.Group("b", (100,))]
    s = G.summarize(groups, 100)
    assert s["largest_size"] == 80 and s["over_1pct"] == [("a", 80)]


@pytest.mark.dumps
def test_universe_has_translations_and_groups_partition_it():
    assert G.missing_translations() == []
    texts = G.load_texts()
    assert len(texts) == 7447
    groups, records = G.build_groups(texts)
    assert sum(len(g.meds) for g in groups) == 7447
    assert len(records) == 7447
