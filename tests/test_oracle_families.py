from hypothesis import given, settings
from hypothesis import strategies as st

from habench.oracle.families import analyze, naive_family, necessity, reference_bfs, subsets


def fam(*sets):
    return frozenset(frozenset(s) for s in sets)


def table_from(D, sufficient, inadmissible=()):
    """Binary table: 1 on the sufficient sets and D, 0 elsewhere (∅ is 0)."""
    suff = {frozenset(s) for s in sufficient} | {frozenset(D)}
    bad = {frozenset(s) for s in inadmissible}
    return {S: int(S in suff) for S in subsets(D) if S not in bad}


def test_ex13_incomplete():
    D = ["dup_ind", "ent_thr", "mask_drug"]
    t = table_from(D, [["ent_thr"], ["dup_ind", "mask_drug"], ["ent_thr", "dup_ind"], ["ent_thr", "mask_drug"]],
                   inadmissible=[["dup_ind"], ["mask_drug"], ["dup_ind", "ent_thr"], ["ent_thr", "mask_drug"]])
    r = analyze(D, t)
    assert r.family == fam(["ent_thr"], ["dup_ind", "mask_drug"])
    assert r.complete is False


def test_ex10_nonmonotone():
    D = ["ent_thr", "icd_thr", "patch:p3"]
    r = analyze(D, table_from(D, [["ent_thr"], ["ent_thr", "patch:p3"]]))
    assert r.family == fam(["ent_thr"])
    assert r.nonmonotone is True and r.complete is True


def test_ex08_unchanged():
    D = ["ent_thr", "patch:p2"]
    t = {frozenset(): 1, frozenset({"ent_thr"}): 0, frozenset({"patch:p2"}): 1, frozenset(D): 1}
    assert analyze(D, t).changed is False


def test_ex16_bfs_and_budget():
    D = ["A", "B", "C"]
    t = table_from(D, [["A"], ["A", "C"], ["B", "C"]])
    r = reference_bfs(D, {"q": t.__getitem__})
    assert [sorted(S) for S in r.evaluated] == [[], ["A", "B", "C"], ["A"], ["B"], ["C"], ["B", "C"]]
    assert r.families["q"] == fam(["A"], ["B", "C"]) and r.complete["q"]
    r5 = reference_bfs(D, {"q": t.__getitem__}, budget=5)
    assert r5.families["q"] == fam(["A"]) and not r5.complete["q"] and r5.exhausted


def test_ex28_completeness_with_inadmissibles():
    D = ["A", "B", "C"]
    ta = table_from(D, [["B", "C"]], inadmissible=[["A"]])
    ra = reference_bfs(D, {"q": ta.__getitem__}, admissible=lambda S: S in ta)
    assert len(ra.evaluated) == 7 and ra.families["q"] == fam(["B", "C"]) and not ra.complete["q"]
    tb = table_from(D, [["A"], ["A", "C"]], inadmissible=[["A", "B"]])
    rb = reference_bfs(D, {"q": tb.__getitem__}, admissible=lambda S: S in tb)
    assert len(rb.evaluated) == 6 and rb.families["q"] == fam(["A"]) and rb.complete["q"]


def test_joint_bfs_prunes_only_when_all_open_queries_prune():
    D = ["A", "B"]
    q1 = table_from(D, [["A"]])
    q2 = table_from(D, [["B"]])
    n = necessity(D, {"q1": q1.__getitem__, "q2": q2.__getitem__})
    assert n == 4  # ∅, D, A, B: A is sufficient for q1 only, B still open for q2


# --------------------------------------------------------------------- A19: differential property tests


@st.composite
def random_case(draw):
    n = draw(st.integers(1, 6))
    D = [f"f{i}" for i in range(n)]
    n_prep = draw(st.integers(0, min(3, n)))
    prep = D[:n_prep]
    prep_subsets = subsets(prep)
    avail = {frozenset(), frozenset(prep)} | {
        s for s in prep_subsets if draw(st.booleans())
    }
    post = D[n_prep:]
    dummy = {f for f in post if draw(st.integers(0, 3)) == 0}
    live = [f for f in D if f not in dummy]
    # state depends only on the live factors; values in {0, 1, 2} to exercise non-binary states
    live_subsets = subsets(live)
    values = {S: draw(st.integers(0, 2)) for S in live_subsets}
    table = {S: values[S - dummy] for S in subsets(D) if (S & set(prep)) in avail}
    return D, table, frozenset(dummy)


@settings(max_examples=400, deadline=None)
@given(random_case())
def test_dp_naive_bfs_agree(case):
    D, table, dummy = case
    r = analyze(D, table)
    naive = naive_family(D, table)
    assert r.family == naive
    if not r.changed:
        return
    target = table[frozenset(D)]
    # every member is sufficient, antichain, every sufficient set contains a member
    assert all(table[S] == target for S in r.family)
    assert not any(a < b for a in r.family for b in r.family)
    assert all(any(F <= S for F in r.family) for S in r.sufficient)
    for dummies in (frozenset(), dummy):
        b = reference_bfs(D, {"q": table.__getitem__}, admissible=lambda S: S in table, dummies={"q": dummies})
        assert b.families["q"] == r.family
        assert b.complete["q"] == r.complete
    assert not any(S & dummy for S in r.family)
