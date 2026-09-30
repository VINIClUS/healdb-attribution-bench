"""Scenario generation on toy evidence (no real data)."""

import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
from test_scenarios_data import MED, MED_FAILED, SEED, toy_group, wide_group

from habench.oracle import toy
from habench.oracle.contrast import MAX_FACTORS
from habench.oracle.hybrids import Hybrids, all_subsets
from habench.pipeline import core
from habench.pipeline.catalog import V1, V2
from habench.scenarios import xfamily
from habench.scenarios.config import load_config
from habench.scenarios.generate import generate, generate_with_report, scenarios_canonical
from habench.types import Presence

HIER = toy.hierarchy()
LABELS = ("F", "N", "M", "O", "X", "I", "P", "ent_thr", "icd_thr", "border", "swap", "extend", "declared", "alt_")


@pytest.fixture(scope="module")
def run():
    groups, ev = toy_group()
    scs, rep = generate_with_report("dev", seed=SEED, groups=groups, evidence=ev, hier=HIER)
    return scs, rep, ev


def by_family(scs, fam):
    return [s for s in scs if s.family == fam]


def hybrids_of(sc, ev):
    return Hybrids(sc.contrast, ev, HIER)


def test_every_family_produces_scenarios(run):
    scs, rep, _ = run
    fams = Counter(s.family for s in scs)
    assert set(fams) == {"N", "F", "M", "O", "X", "I"}
    assert "P" not in fams
    assert fams["N"] == 3 and fams["F"] == 7 and fams["M"] == 5 and fams["O"] == 5
    assert rep.produced and not rep.errors
    assert sum(rep.produced.values()) == len(scs)


def test_contrasts_are_valid_and_bounded(run):
    scs, _, ev = run
    for s in scs:
        c = s.contrast
        c.validate(check_sealed=False)
        assert len(c.D) <= MAX_FACTORS
        assert c.space == "cm" or c.space == "who"
        assert hybrids_of(s, ev).endpoints_reproduce()
    assert len({s.contrast.cid for s in scs}) == len(scs)


def test_space_is_who_except_extend_and_cm_only_contrasts(run):
    scs, _, _ = run
    for s in scs:
        if s.contrast.space == "cm":
            assert s.subfamily in {"extend", "declared_map", "alt_map"}
            assert s.contrast.x0["map"].startswith("cm_") and s.contrast.x1["map"].startswith("cm_")
        else:
            assert s.contrast.space == "who"
    ext = [s for s in by_family(run[0], "M") if s.subfamily == "extend"][0]
    assert ext.contrast.D == ("EXTEND",) and ext.contrast.bundle_map == {"EXTEND": ("map",)}


def test_family_n_has_only_unchanged_queries_confirmed_by_the_oracle(run):
    scs, _, ev = run
    ns = by_family(scs, "N")
    assert {s.subfamily for s in ns} >= {"a_empty_D", "b_map"}
    for s in ns:
        h = hybrids_of(s, ev)
        for _, key in s.queries:
            assert h.state(frozenset(), key) == h.state(frozenset(h.D), key)
        # every candidate key of the group, not just the sampled ones
        r0, rD = h.run(frozenset()), h.run(frozenset(h.D))
        assert r0.present == rD.present
    empty = [s for s in ns if s.subfamily == "a_empty_D"][0]
    assert empty.contrast.D == () and empty.contrast.x0 == empty.contrast.x1 == V1
    bmap = [s for s in ns if s.subfamily == "b_map"][0]
    assert bmap.contrast.D == ("map",) and bmap.contrast.space == "who"


def test_family_n_with_a_changed_query_is_dropped_as_a_generation_error():
    from habench.scenarios.base import Candidate, Ctx, GenerationReport, assess

    groups, ev = toy_group()
    rep = GenerationReport()
    ctx = Ctx("dev", SEED, "g1", groups[0][1], ev.subset(groups[0][1]), HIER, load_config(), rep)
    bad = Candidate("N", "fake", ctx.contrast(V1, V1.with_(ent_thr=0.55)))  # changes the es=0.59 entity
    assert assess(ctx, bad, null=True) is None
    assert rep.errors == [bad.contrast.cid] and rep.dropped["N:null_contrast_has_changed_query"] == 1


def test_non_null_contrasts_have_a_changed_query(run):
    scs, _, ev = run
    for s in scs:
        if s.family == "N":
            continue
        h = hybrids_of(s, ev)
        assert any(h.state(frozenset(), k) != h.state(frozenset(h.D), k) for _, k in s.queries)


def test_family_f_one_factor_plus_border_patch(run):
    scs, _, _ = run
    fs = by_family(scs, "F")
    assert {"border_eq", "border_minus"} <= {s.subfamily for s in fs}
    for s in fs:
        c = s.contrast
        config_factors = [f for f in c.D if not f.startswith("patch:")]
        assert len(config_factors) == 1 and config_factors[0] in {"ent_thr", "icd_thr", "trait"}
        assert {n: v for n, v in c.x0.items if not n.startswith("patch:")} == V1.as_dict()
        if s.subfamily.startswith("border"):
            assert len(c.patches) == 1 and len(c.D) == 2
        else:
            assert len(c.D) == 1 and not c.patches

    def border_value(sub):
        c = next(s for s in fs if s.subfamily == sub).contrast
        (fact,) = [f for f in c.D if not f.startswith("patch:")]
        (value,) = {e.value for e in c.patches[0].edits}
        return c.x1[fact], value

    t1, v = border_value("border_eq")
    assert v == t1  # the patched score sits exactly at the new threshold
    t1, v = border_value("border_minus")
    assert v == t1 - 1e-9 and v < t1


def test_family_m_pairs(run):
    scs, _, _ = run
    ms = by_family(scs, "M")
    assert len(ms) == 5
    for s in ms:
        c = s.contrast
        if s.subfamily == "extend":
            continue
        assert c.D == ("map",) and c.space == "who"
        assert c.x0["map"] != c.x1["map"]
        assert any("granularity" in n for n in s.notes)


def test_family_o_changes_and_swap(run):
    scs, _, _ = run
    os_ = by_family(scs, "O")
    assert {"occ", "sel", "occ+sel"} <= {s.subfamily for s in os_}
    for s in os_:
        assert all(f in {"occ", "sel"} or f.startswith("patch:") for f in s.contrast.D)
    swap = [s for s in os_ if s.subfamily == "swap"][0]
    assert len(swap.contrast.patches) == 1 and swap.contrast.x1["occ"] == "first_upsert"


def test_family_x_parts(run):
    scs, _, ev = run
    xs = by_family(scs, "X")
    bundle = [s for s in xs if s.subfamily == "v1_to_v2_bundle"][0].contrast
    comp = [s for s in xs if s.subfamily == "v1_to_v2_components"][0].contrast
    assert bundle.D == ("V1_TO_V2",) and set(bundle.components("V1_TO_V2")) == set(V1.diff(V2))
    assert set(comp.D) == set(V1.diff(V2)) and len(comp.D) == 6
    ex07 = [s for s in xs if s.subfamily == "iii_ex07"][0].contrast
    assert set(ex07.D) == {"ent_thr", "icd_thr", next(f for f in ex07.D if f.startswith("patch:"))}
    assert ex07.x1["ent_thr"] == 0.55 and ex07.x1["icd_thr"] == 0.55
    assert len([s for s in xs if s.subfamily == "ii_sampled"]) == 3


def test_x_ii_acceptance_rules_hold_on_the_truth_table(run):
    scs, _, ev = run
    for s in [s for s in by_family(scs, "X") if s.subfamily == "ii_sampled"]:
        h = hybrids_of(s, ev)
        assert 3 <= len(h.D) <= MAX_FACTORS
        tables = {k: h.truth_table(k) for _, k in s.queries}
        chg = [t for t in tables.values() if t[frozenset()] != t[frozenset(h.D)]]
        assert chg
        assert any(all(xfamily.is_dummy(f, t) for t in chg) for f in h.D)  # verified no-effect factor
        assert xfamily.has_opposing_pair(h.D, tables.values())  # cancellation
        assert any(f.startswith("patch:") for f in h.D)


def test_shape_helpers_and_quota():
    D = ("a", "b")
    fs = frozenset
    P_, A_ = Presence.PRESENT, Presence.ABSENT
    uni = {fs(): A_, fs({"a"}): P_, fs({"b"}): A_, fs({"a", "b"}): P_}
    assert xfamily.query_shapes(D, uni) == {"unitary"}
    alt = {fs(): A_, fs({"a"}): P_, fs({"b"}): P_, fs({"a", "b"}): P_}
    assert xfamily.query_shapes(D, alt) == {"several"}
    inter = {fs(): A_, fs({"a"}): A_, fs({"b"}): A_, fs({"a", "b"}): P_}
    assert xfamily.query_shapes(D, inter) == {"interaction"}
    D3 = ("a", "b", "c")
    nonmono = {S: A_ for S in all_subsets(D3)}
    nonmono[fs({"a"})] = P_
    nonmono[fs({"a", "b"})] = A_
    nonmono[fs({"a", "c"})] = P_
    nonmono[fs({"a", "b", "c"})] = P_
    nonmono[fs({"b", "c"})] = A_
    assert "nonmonotone" in xfamily.query_shapes(D3, nonmono)
    assert xfamily.query_shapes(D, {S: A_ for S in all_subsets(D)}) == set()
    assert xfamily.is_dummy("b", uni) and not xfamily.is_dummy("a", uni)
    q = xfamily.ShapeQuota({"unitary": 2, "several": 0, "interaction": 0, "nonmonotone": 0})
    assert q.wants(Counter(unitary=1)) and not q.wants(Counter(several=3))
    q.add(Counter(unitary=2))
    assert q.wants(Counter(several=3))  # every quota filled: anything that meets the other rules is accepted


def test_opposing_pair_detector():
    fs = frozenset
    P_, A_ = Presence.PRESENT, Presence.ABSENT
    cancel = {fs(): P_, fs({"a"}): A_, fs({"b"}): P_, fs({"a", "b"}): P_}
    assert xfamily.has_opposing_pair(("a", "b"), [cancel])
    none = {fs(): A_, fs({"a"}): P_, fs({"b"}): A_, fs({"a", "b"}): P_}
    assert not xfamily.has_opposing_pair(("a", "b"), [none])


def test_queries_respect_caps_ratio_and_inclusion(run):
    scs, _, ev = run
    for s in scs:
        h = hybrids_of(s, ev)
        ch = [q for q, k in s.queries if h.state(frozenset(), k) != h.state(frozenset(h.D), k)]
        un = [q for q, _ in s.queries if q not in ch]
        assert len(ch) <= 25 and len(un) <= 25
        if s.family != "N":
            assert len(un) <= max(len(ch), 1)
        assert set(s.inclusion) == {q for q, _ in s.queries}
        assert all(0 < p <= 1 for p in s.inclusion.values())
        assert list(s.queries) == sorted(s.queries, key=lambda q: q[1])


def test_sampling_caps_and_inclusion_probabilities_on_a_wide_group():
    groups, ev, hier = wide_group(60)
    scs = [s for s in generate("dev", seed=SEED, groups=groups, evidence=ev, hier=hier)]
    f = next(s for s in scs if s.family == "F" and s.subfamily == "ent_thr" and s.contrast.x1["ent_thr"] == 0.55)
    h = Hybrids(f.contrast, ev, hier)
    ch = {q: k for q, k in f.queries if h.state(frozenset(), k) != h.state(frozenset(h.D), k)}
    un = {q: k for q, k in f.queries if q not in ch}
    assert len(ch) == 25 and len(un) == 25
    assert all(f.inclusion[q] == pytest.approx(25 / 30) for q in ch)  # 30 changed keys, 25 sampled
    assert all(f.inclusion[q] == pytest.approx(25 / 30) for q in un)  # 30 unchanged keys, 25 sampled
    n = next(s for s in scs if s.subfamily == "a_empty_D")
    assert len(n.queries) == 25 and all(p == pytest.approx(25 / 60) for p in n.inclusion.values())


def test_ineligible_medications_are_counted_not_queried():
    groups, ev = toy_group(with_failed=True)
    scs, rep = generate_with_report("dev", seed=SEED, groups=groups, evidence=ev, hier=HIER)
    assert scs and rep.ineligible["unavailable_med:failed"] > 0
    assert all(k.med != MED_FAILED for s in scs for _, k in s.queries)
    h = Hybrids(scs[0].contrast, ev, HIER)
    assert h.state(frozenset(), next(iter(core.run(V1, ev, HIER).present))) in (Presence.PRESENT, Presence.ABSENT)


def test_determinism_same_process(run):
    scs, _, ev = run
    groups, _ = toy_group()
    again = generate("dev", seed=SEED, groups=groups, evidence=ev, hier=HIER)
    assert scenarios_canonical(again) == scenarios_canonical(scs)
    other = generate("dev", seed=SEED + 1, groups=groups, evidence=ev, hier=HIER)
    assert scenarios_canonical(other) != scenarios_canonical(scs)


def test_determinism_across_processes_with_different_hash_seeds():
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from test_scenarios_data import toy_group, SEED\n"
        "from habench.oracle import toy\n"
        "from habench.scenarios.generate import generate, scenarios_canonical\n"
        "g, ev = toy_group()\n"
        "print(scenarios_canonical(generate('dev', seed=SEED, groups=g, evidence=ev, hier=toy.hierarchy())))\n"
    ) % str(Path(__file__).parent)
    outs = []
    for hs in ("1", "4242"):
        env = {**os.environ, "PYTHONHASHSEED": hs}
        outs.append(subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                                   check=True).stdout)
    assert outs[0] == outs[1] and outs[0].strip()
    groups, ev = toy_group()
    here = scenarios_canonical(generate("dev", seed=SEED, groups=groups, evidence=ev, hier=HIER))
    assert here.strip() == outs[0].strip()


def test_ids_carry_no_family_label_nor_seed(run):
    scs, _, _ = run
    for s in scs:
        c = s.contrast
        ids = [c.cid, *(p.id for p in c.patches), *(q for q, _ in s.queries)]
        assert c.cid.startswith("c") and all(q.startswith("q") for q, _ in s.queries)
        assert all(p.id.startswith("p") for p in c.patches)
        for i in ids:
            assert str(SEED) not in i
            assert i == i.lower()  # hex digests plus a lowercase prefix: no family letter can appear
            assert not any(w in i for w in LABELS if w.islower() and len(w) > 2)
        assert c.to_json()["cid"] == c.cid
        blob = c.canonical()
        assert "family" not in blob and "seed" not in blob and "origin" not in blob


def test_low_multiplicity_groups_skip_family_o():
    ev = toy.evidence({MED: toy.response([toy.entity(1, 0.9, [("C61", 0.9)]), toy.entity(2, 0.8, [("J45.0", 0.8)])])})
    scs, rep = generate_with_report("dev", seed=SEED, groups=[("g", (MED,))], evidence=ev, hier=HIER)
    assert not by_family(scs, "O") and rep.dropped["O:low_multiplicity"] == 1


def test_i_family_divergence_and_alt_variants(run):
    scs, _, ev = run
    by_sub = {s.subfamily: s for s in by_family(scs, "I")}
    t = by_sub["declared_trait"].contrast
    assert t.d0["trait"] == "v1_hyp_le_0.6" and t.x0["trait"] == "v1" and t.D[0] != "trait"
    m = by_sub["declared_map"].contrast
    assert m.space == "cm" and m.x0["map"] == "cm_ungated" and m.d0["map"] == "cm_gated"
    o = by_sub["declared_occ"].contrast
    assert o.x0["occ"] == "first_upsert" and o.d0["occ"] == "last_upsert"
    for sub in ("alt_trait", "alt_occ", "alt_map"):
        c = by_sub[sub].contrast
        assert c.variants1 and not c.variants0 and c.x0 == c.x1  # same label, different behavior
        assert len(c.D) == 1
    for s in by_family(scs, "I"):
        assert hybrids_of(s, ev).endpoints_reproduce()
    assert "alt_threshold" in by_sub or "alt_threshold_border" in by_sub


def test_p_is_never_generated(run):
    scs, rep, _ = run
    assert not any(s.family == "P" for s in scs) and not any(k.startswith("P") for k in rep.produced)
