import numpy as np
import pytest

from habench.oracle import toy
from habench.oracle.contrast import make_contrast
from habench.oracle.hybrids import Hybrids, Inadmissible, realize
from habench.pipeline.catalog import V1
from habench.pipeline.evidence import JsonEdit, Patch
from habench.types import SYSTEM_ICD10_WHO, AssocKey, Presence

MED = 900_000_001
HIER = toy.hierarchy()
KEY = AssocKey(MED, SYSTEM_ICD10_WHO, HIER.version, "C61")


def ev(es=0.59, cs=0.9, traits=(("DIAGNOSIS", 0.9),)):
    return toy.evidence({MED: toy.response([toy.entity(1, es, [("C61", cs)], traits)])})


def test_ex07_states():
    p1 = Patch("p1", (JsonEdit(MED, ("Entities", 0, "Score"), 0.62),))
    c = make_contrast("c", "g", [MED], "who", V1, V1.with_(ent_thr=0.58, icd_thr=0.55), patches=[p1])
    h = Hybrids(c, ev(), HIER)
    table = h.truth_table(KEY)
    assert len(table) == 8
    for S, st in table.items():
        want = Presence.PRESENT if ({"ent_thr", "patch:p1"} & S) else Presence.ABSENT
        assert st == want, S
    assert h.endpoints_reproduce()
    assert h.runs == 8


def test_cache_shares_runs_with_equal_realized_config():
    c = make_contrast("c", "g", [MED], "who", V1, V1.with_(ent_thr=0.58))
    h = Hybrids(c, ev(), HIER)
    h.state(frozenset(), KEY)
    h.state(frozenset(), KEY)
    assert h.runs == 1


def test_variants_are_realized():
    assert realize("ent_thr", 0.6, "alt") == float(np.nextafter(0.6, 2.0))
    assert realize("trait", "v1", "alt") == "v1_hyp_le_0.6"
    assert realize("occ", "last_upsert", "alt") == "first_upsert"
    assert realize("map", "cm_gated", "alt") == "cm_ungated"
    # es exactly at the threshold: present with `>=` (std), absent with `>` (alt)
    c = make_contrast("c", "g", [MED], "who", V1, V1, variants1=["ent_thr"])
    h = Hybrids(c, ev(es=0.60), HIER)
    assert h.D == ("ent_thr",)
    assert h.state(frozenset(), KEY) == Presence.PRESENT
    assert h.state(frozenset({"ent_thr"}), KEY) == Presence.ABSENT


def test_declared_replay_uses_declared_levels_and_run_variants():
    # EX-11: declared d0 trait = v1_hyp_le_0.6 (documentation), executed x0 trait = v1 (code)
    d0 = V1.with_(trait="v1_hyp_le_0.6")
    x1 = V1.with_(ent_thr=0.55)
    c = make_contrast("c", "g", [MED], "who", V1, x1, d0=d0, d1=x1)
    e = ev(es=0.58, traits=(("HYPOTHETICAL", 0.62), ("DIAGNOSIS", 0.9)))
    truth = Hybrids(c, e, HIER)
    replay = Hybrids(c, e, HIER, levels="declared")
    assert truth.D == ("ent_thr",)
    assert replay.D == ("ent_thr", "trait")
    assert truth.state(frozenset({"ent_thr"}), KEY) == Presence.PRESENT
    assert replay.state(frozenset({"ent_thr"}), KEY) == Presence.ABSENT  # v1_hyp_le_0.6 vetoes HYP 0.62
    assert replay.state(frozenset({"ent_thr", "trait"}), KEY) == Presence.PRESENT


def test_unavailable_medication():
    c = make_contrast("c", "g", [MED], "who", V1, V1.with_(ent_thr=0.55))
    h = Hybrids(c, toy.evidence({MED: None}), HIER)
    assert h.state(frozenset(), KEY) == Presence.UNAVAILABLE


def test_prep_admissibility():
    x1 = V1.with_(ent_thr=0.55)
    c = make_contrast("c", "g", [MED], "who", V1, x1, prep=["dup_ind", "mask_drug"],
                      prep_available=[["dup_ind", "mask_drug"]])
    assert c.D == ("dup_ind", "ent_thr", "mask_drug")
    h = Hybrids(c, ev(es=0.58), HIER, prep_evidence={("dup_ind", "mask_drug"): ev(es=0.62)})
    assert h.admissible(frozenset({"ent_thr"}))
    assert not h.admissible(frozenset({"dup_ind"}))
    with pytest.raises(Inadmissible):
        h.run(frozenset({"dup_ind"}))
    assert h.state(frozenset({"dup_ind", "mask_drug"}), KEY) == Presence.PRESENT
