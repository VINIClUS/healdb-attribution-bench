"""Pipeline core on hand-built cases; expected answers derived by hand from the historical semantics."""

from __future__ import annotations

import itertools
import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from habench.pipeline.catalog import V1, V1_EXTEND, V2, Config, hybrid
from habench.pipeline.core import CM, WHO, Attrs, KeySpace, evaluate, funnel, run
from habench.pipeline.evidence import Evidence, JsonEdit, Patch
from habench.pipeline.mapping import Hierarchy
from habench.types import SYSTEM_ICD10_WHO, SYSTEM_ICD10CM, AssocKey, Presence

H = Hierarchy.from_rows(
    [
        {"cd_cat": "I10", "id_cat": 1, "id_group": 1},
        {"cd_cat": "E11", "id_cat": 2, "id_group": 1},
        {"cd_cat": "J45", "id_cat": 3, "id_group": 2},
        {"cd_cat": "K50", "id_cat": 5, "id_group": 2},
    ],
    [
        {"cd_subcat": "E119", "id_subcat": 11, "id_cat": 2},
        {"cd_subcat": "J450", "id_subcat": 12, "id_cat": 3},
    ],
)
DX = ("DIAGNOSIS", 0.9)


def ent(eid, es, concepts, traits=(DX,), tp="DX_NAME"):
    return {
        "Id": eid,
        "Score": es,
        "Type": tp,
        "ICD10CMConcepts": [{"Code": c, "Score": s} for c, s in concepts],
        "Traits": [{"Name": n, "Score": s} for n, s in traits],
    }


def resp(*ents, version="1.0.0") -> str:
    return json.dumps({"Entities": list(ents), "ModelVersion": version, "ResponseMetadata": {"HTTPStatusCode": 200}})


def evid(*rows):
    return Evidence.from_responses(list(rows))


def cmk(med, code, version="1.0.0"):
    return AssocKey(med, SYSTEM_ICD10CM, f"acm:{version}", code)


def whok(med, code):
    return AssocKey(med, SYSTEM_ICD10_WHO, H.version, code)


def single(es, cs, traits=(DX,), code="E11.9", tp="DX_NAME"):
    return evid((1, resp(ent(1, es, [(code, cs)], traits, tp))))


# ---------------------------------------------------------------- V1 occurrence


def test_v1_last_occurrence_sets_scores_and_first_upsert_takes_first():
    ev = evid(
        (2, resp(ent(1, 0.9, [("E11.9", 0.8), ("I10", 0.6)]), ent(2, 0.95, [("E11.9", 0.7)]))),
    )
    last = run(V1, ev, H, CM)
    assert last.present == {cmk(2, "E11.9"), cmk(2, "I10")}
    assert last.attrs[cmk(2, "E11.9")] == Attrs(0.7, 0.95)
    assert last.attrs[cmk(2, "I10")] == Attrs(0.6, 0.9)
    first = run(V1.with_(occ="first_upsert"), ev, H, CM)
    assert first.present == last.present
    assert first.attrs[cmk(2, "E11.9")] == Attrs(0.8, 0.9)


def test_v1_traits_are_unioned_across_occurrences():
    ev = evid(
        (1, resp(
            ent(1, 0.9, [("E11.9", 0.8)], [DX, ("NEGATION", 0.8)]),
            ent(2, 0.95, [("E11.9", 0.7)]),
        )),
    )
    key = cmk(1, "E11.9")
    for occ in ("last_upsert", "first_upsert"):
        assert run(V1.with_(occ=occ), ev, H, CM).state(key) == Presence.ABSENT
    # V2 decides every entity Id alone: the second, non-negated entity keeps the association
    assert run(V2, ev, H, WHO).state(whok(1, "E119")) == Presence.PRESENT


def test_first_upsert_keeps_first_trait_score():
    ev = evid(
        (1, resp(
            ent(1, 0.9, [("I10", 0.8)], [DX, ("HYPOTHETICAL", 0.5)]),
            ent(2, 0.9, [("I10", 0.8)], [DX, ("HYPOTHETICAL", 0.7)]),
        )),
    )
    key = cmk(1, "I10")
    assert run(V1, ev, H, CM).state(key) == Presence.ABSENT  # last score 0.7 > 0.65
    assert run(V1.with_(occ="first_upsert"), ev, H, CM).state(key) == Presence.PRESENT


# ---------------------------------------------------------------- V1 thresholds and traits


@pytest.mark.parametrize(
    ("es", "cs", "present"),
    [(0.6, 0.6, True), (0.5999999, 0.6, False), (0.6, 0.5999999, False), (0.6000001, 0.6000001, True)],
)
def test_v1_thresholds_are_greater_or_equal(es, cs, present):
    r = run(V1, single(es, cs), H, CM)
    assert (cmk(1, "E11.9") in r.present) is present


@pytest.mark.parametrize(
    ("hyp", "level", "present"),
    [
        (0.65, "v1", True),
        (0.66, "v1", False),
        (0.61, "v1", True),
        (0.61, "v1_hyp_le_0.6", False),
        (0.6, "v1_hyp_le_0.6", True),
    ],
)
def test_hypothetical_rule(hyp, level, present):
    ev = single(0.9, 0.9, [DX, ("HYPOTHETICAL", hyp)])
    assert (cmk(1, "E11.9") in run(V1.with_(trait=level), ev, H, CM).present) is present


def test_required_trait_clause():
    key = cmk(1, "E11.9")
    for traits in ([], [("FOO", 0.9)], [("NEGATION_X", 0.9)]):
        ev = single(0.9, 0.9, traits)
        assert run(V1, ev, H, CM).state(key) == Presence.ABSENT
        assert run(V1.with_(trait="v1_no_required"), ev, H, CM).state(key) == Presence.PRESENT
    for name in ("DIAGNOSIS", "SYMPTOM", "SIGN"):
        assert key in run(V1, single(0.9, 0.9, [(name, 0.1)]), H, CM).present
    # HYPOTHETICAL alone counts as required only up to 0.6
    assert key in run(V1, single(0.9, 0.9, [("HYPOTHETICAL", 0.6)]), H, CM).present
    assert key not in run(V1, single(0.9, 0.9, [("HYPOTHETICAL", 0.62)]), H, CM).present


@pytest.mark.parametrize("veto", ["LOW_CONFIDENCE", "NEGATION", "PERTAINS_TO_FAMILY"])
def test_v1_veto_traits(veto):
    assert cmk(1, "E11.9") not in run(V1, single(0.9, 0.9, [DX, (veto, 0.01)]), H, CM).present


# ---------------------------------------------------------------- V2


def test_v2_top1_tie_broken_by_code_ascending():
    ev = evid((1, resp(ent(1, 0.9, [("E11.9", 0.5), ("E11.65", 0.5), ("I10", 0.3)], []))))
    r = run(V2, ev, H, WHO)
    # E11.65 < E11.9 in collation order: top-1 is E11.65, which maps to E11 by fallback
    assert r.present == {whok(1, "E11")}
    assert r.attrs[whok(1, "E11")] == Attrs(0.5, 0.9)


def test_v2_no_map_top1_drops_entity_even_if_concept_two_maps():
    ev = evid((1, resp(ent(1, 0.9, [("Z99.9", 0.9), ("E11.9", 0.8)], []))))
    assert run(V2, ev, H, WHO).present == frozenset()
    assert run(V2.with_(sel="all"), ev, H, WHO).present == {whok(1, "E119")}


def test_v2_per_entity_any_presence_and_max_score():
    both = evid((1, resp(ent(1, 0.75, [("E11.65", 0.4)], []), ent(2, 0.8, [("E11.66", 0.9)], []))))
    r = run(V2, both, H, WHO)
    assert r.present == {whok(1, "E11")}
    assert r.attrs[whok(1, "E11")] == Attrs(0.9, 0.8)
    # the entity with the highest score is vetoed: presence is still any, score is the MAX of the passing ones
    neg = evid((1, resp(ent(1, 0.75, [("E11.65", 0.4)], []), ent(2, 0.8, [("E11.66", 0.9)], [("NEGATION", 0.01)]))))
    r = run(V2, neg, H, WHO)
    assert r.present == {whok(1, "E11")}
    assert r.attrs[whok(1, "E11")] == Attrs(0.4, 0.75)


def test_v2_negation_vetoes_regardless_of_score_and_needs_no_trait():
    assert run(V2, evid((1, resp(ent(1, 0.99, [("E11.9", 0.99)], [("NEGATION", 0.01)])))), H, WHO).present == frozenset()
    assert run(V2, evid((1, resp(ent(1, 0.99, [("E11.9", 0.99)], [])))), H, WHO).present == {whok(1, "E119")}


def test_v2_thresholds_and_type_rule():
    assert run(V2, single(0.7, 0.3, []), H, WHO).present == {whok(1, "E119")}
    assert run(V2, single(0.6999999, 0.3, []), H, WHO).present == frozenset()
    assert run(V2, single(0.7, 0.2999999, []), H, WHO).present == frozenset()
    ev = single(0.9, 0.9, [], tp="TIME_TO_DX_NAME")
    assert run(V2, ev, H, WHO).present == frozenset()
    assert run(V2.with_(trait="neg_only"), ev, H, WHO).present == {whok(1, "E119")}
    assert cmk(1, "E11.9") in run(V1, single(0.9, 0.9, tp="TIME_TO_DX_NAME"), H, CM).present  # V1 has no type rule


# ---------------------------------------------------------------- key spaces


def test_v1_cm_space_key():
    r = run(V1, single(0.9, 0.9), H, CM)
    assert r.present == {AssocKey(1, "ICD-10-CM", "acm:1.0.0", "E11.9")}
    assert r.space == CM


def test_v1_who_space_projects_by_exact_fallback():
    ev = evid((1, resp(ent(1, 0.9, [("E11.9", 0.8)]), ent(2, 0.9, [("E11.65", 0.8)]), ent(3, 0.9, [("I10", 0.8)]))))
    r = run(V1, ev, H, WHO)
    assert r.present == {whok(1, "E119"), whok(1, "E11"), whok(1, "I10")}
    assert all(k.version == H.version for k in r.present)


def test_map_levels_in_who_space():
    ev = evid((1, resp(
        ent(1, 0.9, [("E11.9", 0.8)]),
        ent(2, 0.9, [("E11.65", 0.7)]),
        ent(3, 0.9, [("I10", 0.8)]),
        ent(4, 0.9, [("Z99.9", 0.8)]),
    )))
    assert run(V1.with_(map="who_exact_fb"), ev, H, WHO).present == {whok(1, "E119"), whok(1, "E11"), whok(1, "I10")}
    assert run(V1.with_(map="who_exact"), ev, H, WHO).present == {whok(1, "E119"), whok(1, "I10")}
    r = run(V1.with_(map="who_cat3"), ev, H, WHO)
    assert r.present == {whok(1, "E11"), whok(1, "I10")}
    assert r.attrs[whok(1, "E11")].score == 0.8  # E11.9 and E11.65 merge; best record wins
    assert r.unmapped == frozenset()


def test_v2_in_cm_space_raises():
    with pytest.raises(ValueError):
        run(V2, single(0.9, 0.9, []), H, CM)
    with pytest.raises(ValueError):
        KeySpace("icd")


def test_cm_ungated_unmapped_go_to_unmapped_not_present():
    ev = evid((1, resp(ent(1, 0.9, [("Z99.9", 0.9)]), ent(2, 0.9, [("E11.9", 0.9)]))))
    r = run(V1_EXTEND, ev, H, WHO)
    assert r.present == {whok(1, "E119")}
    assert r.unmapped == {(1, "Z99.9")}
    assert cmk(1, "Z99.9") in run(V1_EXTEND, ev, H, CM).present
    assert run(V1_EXTEND, ev, H, CM).unmapped == frozenset()
    gated = run(V1, ev, H, WHO)  # gated: the record dies at the gate, it is not an unmapped record
    assert gated.unmapped == frozenset()
    assert gated.present == {whok(1, "E119")}


# ---------------------------------------------------------------- presence state


def test_state_unavailable_and_absent():
    ev = Evidence.from_responses(
        [(1, resp(ent(1, 0.9, [("E11.9", 0.9)]))), (2, resp()), (3, None), (4, "garbage")], meds=[1, 2, 3, 4, 5]
    )
    r = run(V1, ev, H, CM)
    assert r.state(cmk(1, "E11.9")) == Presence.PRESENT
    assert r.state(cmk(1, "I10")) == Presence.ABSENT
    assert r.state(cmk(2, "E11.9")) == Presence.ABSENT
    for med in (3, 4, 5):
        assert r.state(cmk(med, "E11.9")) == Presence.UNAVAILABLE
    assert r.status == {1: "ok", 2: "empty", 3: "failed", 4: "failed", 5: "missing"}


# ---------------------------------------------------------------- funnel and trace


def _funnel_evidence():
    return evid((1, resp(
        ent(1, 0.9, [("Z99.9", 0.9)]),  # map
        ent(2, 0.9, [("E11.9", 0.9)], [DX, ("NEGATION", 0.8)]),  # trait_veto
        ent(3, 0.9, [("E11.65", 0.9)], [DX, ("HYPOTHETICAL", 0.9)]),  # trait_hyp
        ent(4, 0.5, [("J45.9", 0.9)]),  # scores
        ent(5, 0.9, [("J45.0", 0.9)], [("FOO", 0.9)]),  # trait_required
        ent(6, 0.9, [("I10", 0.9)]),  # passes
    )))


def test_funnel_counts():
    e = evaluate(V1, _funnel_evidence(), H)
    assert funnel(e) == [
        ("records", 6), ("map", 5), ("trait_veto", 4), ("trait_hyp", 3),
        ("scores", 2), ("trait_required", 1), ("trait_type", 1),
    ]


def test_trace_has_one_decision_per_record_and_stage():
    r = run(V1, _funnel_evidence(), H, CM, trace=True)
    tr = r.trace
    assert tr is not None and tr.meds == (1,)
    assert len(tr.records) == 6 and len(tr.candidates) == 6
    stages = ("map", "trait_veto", "trait_hyp", "icd_thr", "ent_thr", "trait_required", "trait_type")
    assert len(tr.decisions) == 6 * len(stages)
    rid = {row.code: row.rid for row in tr.records}
    for row in tr.records:
        got = [d.stage for d in tr.decisions if d.ref == row.rid]
        assert got == list(stages)
    assert all(isinstance(d.reason, str) and d.reason for d in tr.decisions)
    expected = {
        "Z99.9": {"map"}, "E11.9": {"trait_veto"}, "E11.65": {"trait_hyp"},
        "J45.9": {"ent_thr"}, "J45.0": {"trait_required"}, "I10": set(),
    }
    for code, stg in expected.items():
        assert {d.stage for d in tr.discards() if d.ref == rid[code]} == stg
    assert all(not d.verdict for d in tr.discards())
    (gate,) = [d for d in tr.discards() if d.ref == rid["Z99.9"]]
    assert "fails the hierarchy gate" in gate.reason
    (thr,) = [d for d in tr.discards() if d.ref == rid["J45.9"]]
    assert "<" in thr.reason and "0.5" in thr.reason
    key_row = {row.code: row.key for row in tr.records}
    assert key_row["I10"] == cmk(1, "I10")


def test_trace_off_by_default_and_restricted_to_meds():
    ev = evid((1, resp(ent(1, 0.9, [("I10", 0.9)]))), (2, resp(ent(1, 0.9, [("I10", 0.9)]))))
    assert run(V1, ev, H, CM).trace is None
    tr = run(V1, ev, H, CM, trace=True, trace_meds=frozenset({2})).trace
    assert tr.meds == (2,) and {r.med for r in tr.records} == {2}


# ---------------------------------------------------------------- patches


def _patch_setup(cs=0.59):
    ev = evid((1, resp(ent(1, 0.9, [("E11.9", cs)]))))
    p = Patch("p1", (JsonEdit(1, ("Entities", 0, "ICD10CMConcepts", 0, "Score"), 0.62),))
    return ev, {"p1": p}


def test_patch_factor_changes_outcome_and_needs_registry():
    ev, reg = _patch_setup()
    key = cmk(1, "E11.9")
    on = V1.with_items({"patch:p1": True})
    assert run(V1, ev, H, CM).state(key) == Presence.ABSENT
    assert run(on, ev, H, CM, patches=reg).state(key) == Presence.PRESENT
    assert run(on, ev, H, CM, patches=reg).attrs[key].score == 0.62
    with pytest.raises(KeyError):
        run(on, ev, H, CM)
    with pytest.raises(KeyError):
        run(on, ev, H, CM, patches={"other": reg["p1"]})
    off = V1.with_items({"patch:p1": False})
    assert run(off, ev, H, CM).state(key) == Presence.ABSENT
    assert ev.patches == frozenset()  # original evidence untouched


def test_protocol_7_2_example_hybrids():
    ev, reg = _patch_setup()
    key = cmk(1, "E11.9")
    x0 = V1.with_items({"patch:p1": False})
    x1 = V1.with_items({"patch:p1": True, "icd_thr": 0.58})
    d = x0.diff(x1)
    assert d == {"icd_thr", "patch:p1"}
    state = {}
    for r in range(len(d) + 1):
        for s in itertools.combinations(sorted(d), r):
            state[frozenset(s)] = run(hybrid(x0, x1, frozenset(s)), ev, H, CM, patches=reg).state(key)
    assert state[frozenset()] == Presence.ABSENT
    assert state[frozenset({"icd_thr"})] == Presence.PRESENT
    assert state[frozenset({"patch:p1"})] == Presence.PRESENT
    assert state[frozenset(d)] == Presence.PRESENT
    target = state[frozenset(d)]
    sufficient = [s for s, v in state.items() if v == target]
    minimal = {s for s in sufficient if not any(t < s for t in sufficient)}
    assert minimal == {frozenset({"icd_thr"}), frozenset({"patch:p1"})}


# ---------------------------------------------------------------- determinism and hybrids


def _toy_rows():
    return [
        (1, resp(ent(1, 0.9, [("E11.9", 0.8), ("I10", 0.5)]), ent(2, 0.65, [("E11.9", 0.4)], [("HYPOTHETICAL", 0.7)]))),
        (2, resp(ent(1, 0.72, [("Z99.9", 0.9), ("E11.65", 0.6)], []), ent(1, 0.6, [("J45.0", 0.35)], [DX]))),
        (3, resp(ent(1, 0.75, [("E11.66", 0.55)], [("SIGN", 0.2)], "TIME_TO_DX_NAME"), ent(2, 0.9, [("E11.65", 0.6)]))),
        (4, resp()),
        (5, None),
    ]


def test_runs_are_deterministic_across_fresh_evidence():
    a = run(V1, Evidence.from_responses(_toy_rows()), H, WHO)
    b = run(V1, Evidence.from_responses(_toy_rows()), H, WHO)
    assert a == b
    ev = Evidence.from_responses(_toy_rows())
    assert run(V2, ev, H, WHO) == run(V2, ev, H, WHO)


def test_all_hybrids_of_v1_v2_run_and_are_deterministic():
    d = sorted(V1.diff(V2))
    assert len(d) == 6
    subsets = [frozenset(c) for r in range(7) for c in itertools.combinations(d, r)]
    assert len(subsets) == 64
    ev1, ev2 = Evidence.from_responses(_toy_rows()), Evidence.from_responses(_toy_rows())
    first = {s: run(hybrid(V1, V2, s), ev1, H, WHO) for s in subsets}
    second = {s: run(hybrid(V1, V2, s), ev2, H, WHO) for s in reversed(subsets)}
    assert first == second
    assert first[frozenset()].present == run(V1, ev1, H, WHO).present
    assert first[frozenset(d)].present == run(V2, ev1, H, WHO).present
    assert first[frozenset()].present != first[frozenset(d)].present


# ---------------------------------------------------------------- properties

_GRID = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
_CODES = ["E11.9", "E11.65", "E11.66", "I10", "J45.0", "J45.9", "Z99.9", "K50"]
_TRAITS = st.lists(
    st.tuples(
        st.sampled_from(["DIAGNOSIS", "SYMPTOM", "SIGN", "NEGATION", "HYPOTHETICAL", "LOW_CONFIDENCE"]),
        st.one_of(st.none(), _GRID),
    ),
    max_size=3,
    unique_by=lambda t: t[0],
)


@st.composite
def _entity(draw, eid):
    concepts = []
    if draw(st.booleans()):
        codes = draw(st.lists(st.sampled_from(_CODES), min_size=5, max_size=5, unique=True))
        scores = sorted(draw(st.lists(_GRID, min_size=5, max_size=5, unique=True)), reverse=True)
        concepts = list(zip(codes, scores))
    return ent(eid, draw(_GRID), concepts, draw(_TRAITS), draw(st.sampled_from(["DX_NAME", "TIME_TO_DX_NAME"])))


@st.composite
def _corpus(draw):
    n = draw(st.integers(1, 3))
    return Evidence.from_responses([(1, resp(*[draw(_entity(i + 1)) for i in range(n)]))])


_BASE = st.fixed_dictionaries(
    {
        "occ": st.sampled_from(["last_upsert", "per_entity_any", "first_upsert"]),
        "sel": st.sampled_from(["all", "top1"]),
        "trait": st.sampled_from(["v1", "v2", "v1_hyp_le_0.6", "v1_no_required", "neg_only"]),
        "map": st.sampled_from(["cm_gated", "cm_ungated", "who_exact_fb", "who_exact", "who_cat3"]),
    }
)


@pytest.mark.parametrize("name", ["ent_thr", "icd_thr"])
@settings(max_examples=60, deadline=None)
@given(data=st.data())
def test_raising_a_threshold_never_adds_keys(name, data):
    ev = data.draw(_corpus())
    base = data.draw(_BASE)
    lo, hi = sorted([data.draw(_GRID), data.draw(_GRID)])
    cfg = Config.of({"ent_thr": 0.6, "icd_thr": 0.6, **base})
    r_lo = run(cfg.with_items({name: lo}), ev, H, WHO)
    r_hi = run(cfg.with_items({name: hi}), ev, H, WHO)
    assert r_hi.present <= r_lo.present
    assert r_hi.unmapped <= r_lo.unmapped
