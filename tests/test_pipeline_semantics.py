"""Soundness of `semantics.dummy` against brute force over every hybrid of the contrast."""

import itertools
import json
import random

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from habench.pipeline import catalog, core, semantics
from habench.pipeline.catalog import V1, V2, Config, hybrid
from habench.pipeline.evidence import Evidence, JsonEdit, Patch
from habench.pipeline.mapping import Hierarchy

HIER = Hierarchy.from_rows(
    [{"cd_cat": "A01", "id_cat": 1, "id_group": 1}, {"cd_cat": "B02", "id_cat": 2, "id_group": 1}],
    [{"cd_subcat": "A011", "id_subcat": 10, "id_cat": 1}],
)


def _entity(eid, score, concepts, traits=(), tp="DX_NAME"):
    return {
        "Id": eid, "Type": tp, "Score": score, "Text": "x", "Category": "MEDICAL_CONDITION",
        "Traits": [{"Name": n, "Score": s} for n, s in traits],
        "ICD10CMConcepts": [{"Code": c, "Score": s, "Description": c} for c, s in concepts],
    }


def _response(*entities):
    return json.dumps({"Entities": list(entities), "ModelVersion": "m", "ResponseMetadata": {"RequestId": "r"}})


def _brute(ev, hier, x0, x1, space, patches=None):
    D = sorted(x0.diff(x1))
    res = {
        frozenset(S): core.run(hybrid(x0, x1, frozenset(S)), ev, hier, space, patches=patches).present
        for r in range(len(D) + 1)
        for S in itertools.combinations(D, r)
    }
    return D, res


def _check_sound(ev, hier, x0, x1, space=core.WHO, patches=None):
    D, res = _brute(ev, hier, x0, x1, space, patches)
    keys = set().union(*res.values())
    proved = 0
    for a in sorted(keys):
        for f in D:
            if semantics.dummy(f, a, x0, x1, ev, hier, space, patches):
                proved += 1
                for S in res:
                    if f not in S:
                        assert (a in res[S]) == (a in res[S | {f}]), (f, a, sorted(S))
    return proved


def test_dummy_threshold_band_and_map():
    ev = Evidence.from_responses([
        (1, _response(_entity(1, 0.95, [("A01.1", 0.9), ("B02", 0.2)], [("DIAGNOSIS", 0.9)]))),
        (2, _response(_entity(1, 0.65, [("A01", 0.5), ("B02.9", 0.4)], [("SIGN", 0.8)]))),
    ])
    a = next(k for k in core.run(V1, ev, HIER).present if k.med == 1)
    assert semantics.dummy("ent_thr", a, V1, V2, ev, HIER) is True  # 0.95 outside [0.60, 0.70)
    assert semantics.dummy("map", a, V1, V2, ev, HIER) is True  # gate == NO_MAP drop in WHO space
    b_key = core.run(V1.with_(icd_thr=0.30, ent_thr=0.60), ev, HIER).present
    b = next(k for k in b_key if k.med == 2 and k.code == "A01")
    assert semantics.dummy("ent_thr", b, V1, V2, ev, HIER) is None  # 0.65 inside the band
    assert _check_sound(ev, HIER, V1, V2) > 0


def test_dummy_never_false():
    ev = Evidence.from_responses([(1, _response(_entity(1, 0.65, [("A01", 0.65)], [("DIAGNOSIS", 0.9)])))])
    a = next(iter(core.run(V1, ev, HIER).present))
    for f in sorted(V1.diff(V2)):
        assert semantics.dummy(f, a, V1, V2, ev, HIER) in (True, None)


def test_dummy_patch_on_other_med_and_sound_with_patch():
    ev = Evidence.from_responses([
        (1, _response(_entity(1, 0.9, [("A01", 0.59)], [("DIAGNOSIS", 0.9)]))),
        (2, _response(_entity(1, 0.9, [("B02", 0.9)], [("DIAGNOSIS", 0.9)]))),
    ])
    p = Patch("p1", (JsonEdit(1, ("Entities", 0, "ICD10CMConcepts", 0, "Score"), 0.62),))
    x0 = V1.with_items({"patch:p1": False})
    x1 = x0.with_items({"patch:p1": True, "icd_thr": 0.58})
    patches = {"p1": p}
    b = next(k for k in core.run(x0, ev, HIER, patches=patches).present if k.med == 2)
    assert semantics.dummy("patch:p1", b, x0, x1, ev, HIER, patches=patches) is True
    assert _check_sound(ev, HIER, x0, x1, patches=patches) >= 1


def _random_response(rng):
    codes = ["A01", "A01.1", "A01.9", "B02", "B02.3", "C99.1", "A011"]
    ents = []
    for i in range(rng.randint(1, 4)):
        k = rng.choice([0, 5])
        scores = sorted((round(rng.uniform(0.2, 0.95), 3) for _ in range(k)), reverse=True)
        if k > 1 and scores[0] == scores[1]:
            scores[0] += 0.001
        eid = rng.choice([i + 1, 1])  # sometimes repeat an Id
        traits = rng.sample(
            [("DIAGNOSIS", 0.8), ("NEGATION", 0.7), ("HYPOTHETICAL", rng.choice([0.5, 0.62, 0.7])),
             ("SIGN", 0.6), ("LOW_CONFIDENCE", 0.5)],
            rng.randint(0, 3),
        )
        ents.append(_entity(eid, round(rng.uniform(0.5, 0.95), 3),
                            [(rng.choice(codes), s) for s in scores], traits,
                            rng.choice(["DX_NAME", "DX_NAME", "TIME_TO_DX_NAME"])))
    return _response(*ents)


@pytest.mark.parametrize("seed", range(12))
def test_dummy_sound_random_corpora(seed):
    rng = random.Random(seed)
    ev = Evidence.from_responses([(m, _random_response(rng)) for m in range(1, 7)])
    x1 = Config.of({**V2.as_dict(), "trait": rng.choice(["v2", "neg_only", "v1_hyp_le_0.6"]),
                    "map": rng.choice(["who_exact_fb", "who_cat3", "who_exact"])})
    _check_sound(ev, HIER, V1, x1)
    _check_sound(ev, HIER, V1, V1.with_(map="cm_ungated", ent_thr=0.55), core.CM)


# ---- property: soundness against brute force, duplicate Ids and ties (SPEC 4.6) ------------------------

_CODES = ("A01", "A01.1", "B02", "C99.1")  # few codes: the same code often wins in two Id groups (EX-29)
_SCORES = (0.3, 0.55, 0.6, 0.65, 0.7, 0.9)  # on and around every catalogued threshold, with ties
_TRAITS = st.sampled_from([
    ("DIAGNOSIS", 0.8), ("SIGN", 0.6), ("SYMPTOM", 0.9), ("NEGATION", 0.7), ("LOW_CONFIDENCE", 0.5),
    ("PERTAINS_TO_FAMILY", 0.7), ("HYPOTHETICAL", 0.55), ("HYPOTHETICAL", 0.62), ("HYPOTHETICAL", 0.7),
])
_ENTITY = st.builds(
    lambda eid, es, concepts, traits, tp: _entity(eid, es, concepts, traits, tp),
    st.integers(1, 2),  # two Ids for up to four entities: duplicate Ids are frequent
    st.sampled_from(_SCORES),
    st.lists(st.tuples(st.sampled_from(_CODES), st.sampled_from(_SCORES)), max_size=3),
    st.lists(_TRAITS, max_size=3),
    st.sampled_from(["DX_NAME", "DX_NAME", "TIME_TO_DX_NAME"]),
)
_CM_MAPS = ("cm_gated", "cm_ungated")


@st.composite
def _contrast(draw, fixed=None):
    """(x0, x1, space): each post factor draws its two levels independently, so |D| ranges over 0..6.
    `fixed` maps factors to a forced (x0, x1) pair of levels."""
    space = draw(st.sampled_from([core.CM, core.WHO]))
    maps = _CM_MAPS if space == core.CM else tuple(catalog.MAP_LEVELS)
    levels = {f: catalog.FACTORS[f].levels for f in catalog.POST_FACTORS} | {"map": maps}
    x0, x1 = ({f: draw(st.sampled_from(levels[f])) for f in catalog.POST_FACTORS} for _ in range(2))
    for f, (l0, l1) in (fixed or {}).items():
        x0[f], x1[f] = l0, l1
    return Config.of(x0), Config.of(x1), space


_MEDS = st.lists(st.lists(_ENTITY, min_size=1, max_size=4), min_size=1, max_size=2)
_PROPERTY = settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def _sound(meds, contrast):
    x0, x1, space = contrast
    ev = Evidence.from_responses([(m, _response(*ents)) for m, ents in enumerate(meds, 1)])
    _check_sound(ev, HIER, x0, x1, space)


@_PROPERTY
@given(meds=_MEDS, contrast=_contrast())
def test_dummy_sound_property(meds, contrast):
    _sound(meds, contrast)


_SEL_ENTITY = st.builds(  # traits that pass every rule, few codes: presence turns on scores and order
    lambda eid, es, concepts: _entity(eid, es, concepts, [("DIAGNOSIS", 0.9)]),
    st.integers(1, 2),
    st.sampled_from(_SCORES),
    st.lists(st.tuples(st.sampled_from(("A01", "B02")), st.sampled_from(_SCORES)), min_size=1, max_size=2),
)


@settings(max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    meds=st.lists(st.lists(_SEL_ENTITY, min_size=3, max_size=4), min_size=1, max_size=1),
    contrast=_contrast(fixed={"sel": ("all", "top1"), "occ": ("last_upsert", "last_upsert"), "map": ("cm_gated", "cm_gated")}),
)
def test_dummy_sound_property_sel_under_upsert(meds, contrast):
    """Rule 2 with duplicate Ids: the top1 output order can reverse a code's candidates (EX-29/EX-30)."""
    _sound(meds, contrast)


def test_ex30_sel_order_condition():
    """SPEC EX-29/EX-30: both C61 candidates survive top1 but in reverse order; `sel` is not a dummy."""
    ev = Evidence.from_responses([(1, _response(
        _entity(2, 0.90, [("R50.9", 0.50)], [("DIAGNOSIS", 0.9)]),
        _entity(1, 0.90, [("C61", 0.90)], [("DIAGNOSIS", 0.9)]),
        _entity(2, 0.50, [("C61", 0.95)], [("DIAGNOSIS", 0.9)]),
    ))])
    hier = Hierarchy.from_rows(
        [{"cd_cat": "C61", "id_cat": 1, "id_group": 1}, {"cd_cat": "R50", "id_cat": 2, "id_group": 1}],
        [{"cd_subcat": "R509", "id_subcat": 10, "id_cat": 2}],
    )
    x1 = V1.with_(sel="top1")
    a = next(iter(core.run(x1, ev, hier, core.CM).present))
    assert a.code == "C61" and not core.run(V1, ev, hier, core.CM).present
    assert semantics.dummy("sel", a, V1, x1, ev, hier, core.CM) is None


@pytest.mark.dumps
def test_dummy_sound_on_v1_sample():
    """Brute-force soundness over the real V1->V2 contrast on a seeded sample of medications."""
    from habench.pipeline.evidence import load_evidence
    from habench.pipeline.mapping import load_hierarchy

    full = load_evidence("v1")
    hier = load_hierarchy("v1")
    meds = random.Random(20260930).sample(list(full.meds), 150)
    ev = full.subset(meds)
    D, res = _brute(ev, hier, V1, V2, core.WHO)
    keys = set().union(*res.values())
    proved = {f: 0 for f in D}
    for a in sorted(keys):
        for f in D:
            if semantics.dummy(f, a, V1, V2, ev, hier):
                proved[f] += 1
                for S in res:
                    if f not in S:
                        assert (a in res[S]) == (a in res[S | {f}]), (f, a, sorted(S))
    assert proved["map"] == len(keys)  # the V1 gate and V2's NO_MAP drop are the same predicate
    assert proved["ent_thr"] > 0 and proved["occ"] > 0
