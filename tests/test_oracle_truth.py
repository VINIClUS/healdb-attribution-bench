import json

import pytest

from habench.oracle import dummies, toy
from habench.oracle.contrast import make_contrast
from habench.oracle.hybrids import Hybrids
from habench.oracle.truth import CellSpec, ContrastTruth, Identification, build_truth, read_truth, write_truth
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
    return build_truth(h, [("q1", C61), ("q2", R50)], partition="dev", scenario_family="X", cells=CELLS,
                       dummy=lambda key, f: dummies.certificate(h, key, f), **kw)


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
