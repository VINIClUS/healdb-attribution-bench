"""Soundness of `semantics.dummy` against brute force over every hybrid of the contrast."""

import itertools
import json
import random

import pytest

from habench.pipeline import core, semantics
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
