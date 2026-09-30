import json

import pytest

from habench.oracle import toy
from habench.oracle.contrast import make_contrast
from habench.oracle.hybrids import Hybrids
from habench.oracle.truth import (
    CellSpec,
    ContrastTruth,
    Identification,
    build_truth,
    default_expressible,
    read_truth,
    write_truth,
)
from habench.pipeline.catalog import V1
from habench.pipeline.evidence import JsonEdit, Patch
from habench.types import SYSTEM_ICD10_WHO, AssocKey, Presence, SealedError

MED = 900_000_001
HIER = toy.hierarchy()
C61 = AssocKey(MED, SYSTEM_ICD10_WHO, HIER.version, "C61")
R50 = AssocKey(MED, SYSTEM_ICD10_WHO, HIER.version, "R509")
CELLS = [CellSpec.of("L2-R", "R-A"), CellSpec.of("L1", "R-C"), CellSpec.of("L2-M", "R-C"), CellSpec.of("L2-R-A3", "R-A")]


def ex07_truth(**kw) -> ContrastTruth:
    p1 = Patch("p1", (JsonEdit(MED, ("Entities", 0, "Score"), 0.62),))
    c = make_contrast("c", "g", [MED], "who", V1, V1.with_(ent_thr=0.58, icd_thr=0.55), patches=[p1])
    e = toy.evidence({MED: toy.response([toy.entity(1, 0.59, [("C61", 0.9)]), toy.entity(2, 0.9, [("R50.9", 0.9)])])})
    h = Hybrids(c, e, HIER)
    return build_truth(h, [("q1", C61), ("q2", R50)], partition="dev", scenario_family="X", cells=CELLS, **kw)


def test_ex07_truth():
    t = ex07_truth()
    q1, q2 = t.queries
    assert t.origin == "semisynthetic"
    assert (q1.x0, q1.x1, q1.changed, q1.complete, q1.nonmonotone) == (
        Presence.ABSENT, Presence.PRESENT, True, True, False)
    assert q1.F_star == frozenset({frozenset({"ent_thr"}), frozenset({"patch:p1"})})
    assert q1.cell("L2-R", "R-A") == "identificado"
    with pytest.raises(KeyError):
        q1.cell("L1", "R-C")  # U needed and no identification function given
    assert q2.cell("L2-R", "R-A") == "inalterado"
    assert q1.sufficient({"ent_thr", "icd_thr"}) and not q1.sufficient({"icd_thr"})
    assert q1.is_dummy("icd_thr") and not q1.is_dummy("ent_thr")
    assert t.necessity[("L1", "R-C")] == 0 and t.necessity[("L2-M", "R-C")] == 0
    # R50.9 is unchanged; for C61 icd_thr is certified dummy: ∅, D, {ent_thr}, {patch:p1} = 4
    assert t.necessity[("L2-R", "R-A")] == 4
    assert t.budget_abstention_appropriate("L2-R", "R-A", 3)
    assert not t.budget_abstention_appropriate("L2-R", "R-A", 16)
    assert t.valid


def test_identification_function_fills_cells_that_need_u():
    def ident(q, cs):
        return Identification(frozenset({q.family}), frozenset({q.family, frozenset({frozenset({"icd_thr"})})}), True)

    q1 = ex07_truth(ident=ident).queries[0]
    assert q1.cell("L1", "R-C") == "indeterminado"
    assert q1.cell("L2-R", "R-A") == "identificado"


def test_identification_states():
    F1 = frozenset({frozenset({"a"})})
    F2 = frozenset({frozenset({"b"})})
    assert Identification(frozenset({F1, F2}), frozenset({F1, F2}), False).state == "ambiguo"
    assert Identification(frozenset({F1}), frozenset({F1}), True).state == "identificado"
    assert Identification(frozenset({F1}), frozenset({F1}), False).state == "indeterminado"
    assert Identification(frozenset({F1}), frozenset({F1, F2}), True).state == "indeterminado"
    with pytest.raises(ValueError):
        Identification(frozenset({F1, F2}), frozenset({F1}), True)


def test_cell_specs():
    assert not CellSpec.of("L2-R", "R-A").u_needed(False)
    assert CellSpec.of("L2-R", "R-C").u_needed(False)
    assert CellSpec.of("L2-R-A3", "R-A").u_needed(False)
    assert CellSpec.of("L2-M-A2", "R-A").u_needed(False) is True
    assert CellSpec.of("L2-R", "R-B").u_needed(True)
    assert CellSpec.of("N1", "R-A").u_needed(False)
    assert CellSpec.of("L2-M-C2", "R-A").full_response is False
    with pytest.raises(ValueError):
        CellSpec.of("L1", "R-A")


def test_json_round_trip(tmp_path):
    t = ex07_truth()
    path = tmp_path / "truth" / "c.json"
    write_truth(t, path)
    back = read_truth(path)
    assert back.to_json() == t.to_json()
    assert json.loads(path.read_text())["origin"] == "semisynthetic"


def test_test_partition_is_never_written(tmp_path):
    t = ex07_truth()
    sealed = ContrastTruth(t.contrast, "test", t.scenario_family, t.queries, t.necessity)
    with pytest.raises(SealedError):
        write_truth(sealed, tmp_path / "x.json")


def test_ex11_declared_cell_necessity_uses_declared_contrast():
    """EX-11 under L2-R-A3 × R-A: the replay D is {ent_thr, trait}; trait must not be pruned as dummy."""
    d0 = V1.with_(trait="v1_hyp_le_0.6")
    x1 = V1.with_(ent_thr=0.55)
    c = make_contrast("c11", "g", [MED], "who", V1, x1, d0=d0, d1=x1)
    traits = (("HYPOTHETICAL", 0.62), ("DIAGNOSIS", 0.9))
    e = toy.evidence({MED: toy.response([toy.entity(1, 0.58, [("C61", 0.9)], traits)])})
    h = Hybrids(c, e, HIER)
    hd = Hybrids(c, e, HIER, levels="declared")
    cells = [CellSpec.of("L2-R-A3", "R-A"), CellSpec.of("L2-R", "R-A")]
    t = build_truth(h, [("q", C61)], partition="dev", scenario_family="I", cells=cells, declared_hybrids=hd)
    # declared replay: ∅ absent, D present, {ent_thr} absent, {trait} absent -> ∅, D, ent_thr, trait
    assert t.necessity[("L2-R-A3", "R-A")] == 4
    assert t.necessity[("L2-R", "R-A")] == 2  # executed D = {ent_thr}


def test_recorded_mismatch_marks_invalid():
    t = ex07_truth(recorded=dict(q1=(Presence.ABSENT, Presence.ABSENT)))
    assert not t.valid and "q1" in t.invalid_reason
    assert ex07_truth(recorded=dict(q1=(Presence.ABSENT, Presence.PRESENT))).valid


def test_n1_n2_expressible():
    x1 = V1.with_(ent_thr=0.55, trait="v2")
    c = make_contrast("cn", "g", [MED], "who", V1, x1)
    h = Hybrids(c, toy.evidence({MED: toy.response([toy.entity(1, 0.9, [("C61", 0.9)])])}), HIER)
    assert default_expressible(CellSpec.of("N2", "R-A"), h, frozenset({"ent_thr"}))
    assert not default_expressible(CellSpec.of("N2", "R-A"), h, frozenset({"trait"}))
    assert not default_expressible(CellSpec.of("N1", "R-A"), h, frozenset({"trait"}))  # v2 is not a V1 rule
    assert default_expressible(CellSpec.of("L2-R", "R-A"), h, frozenset({"trait"}))
