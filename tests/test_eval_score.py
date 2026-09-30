"""`eval.score` against the SPEC scoring, validation and backing examples, on oracle-built truth."""

import itertools
import json
from pathlib import Path

import pytest

from habench.eval.score import OUTCOMES, Backing, Certificate, Output, backing, score_cell, score_query, validate
from habench.oracle import toy
from habench.oracle.contrast import make_contrast
from habench.oracle.hybrids import Hybrids
from habench.oracle.truth import CellSpec, Identification, build_truth
from habench.pipeline.catalog import V1
from habench.pipeline.evidence import JsonEdit, Patch
from habench.types import SYSTEM_ICD10CM, AssocKey, OutputState

DATA = json.loads((Path(__file__).parent / "data" / "spec_examples.json").read_text(encoding="utf-8"))
EXAMPLES = {e["id"]: e for e in DATA["examples"]}
MED = 900_000_001
HIER = toy.hierarchy()


def fam(sets):
    return frozenset(frozenset(S) for S in sets)


def fams(x):
    return None if x is None else frozenset(fam(F) for F in x)


@pytest.mark.parametrize("ex", [e for e in DATA["examples"] if e["kind"] == "scoring"], ids=lambda e: e["id"])
def test_scoring_examples(ex):
    o = ex["output"]
    out = validate(Output.of(o["state"], o["families"]))
    got = score_cell(
        ex["cell"], out, backing_=Backing(o["certificates_true"], o["backed"]),
        F_star=None if ex["F_star"] is None else fam(ex["F_star"]), W_lo=fams(ex["W_lo"]), W_hi=fams(ex["W_hi"]),
        F_adm=None if ex["F_adm"] is None else fam(ex["F_adm"]), necessity=ex["needed"], budget=ex["budget"],
    )
    assert got == ex["expected"]


def test_scoring_table_is_total():
    F1, F2 = fam([["ent_thr"]]), fam([["ent_thr", "trait"]])
    for cell, state in itertools.product(
        ("identificado", "ambiguo", "indeterminado", "incompleta", "inalterado"), OutputState
    ):
        families = {"explicacao_verificada": [[["ent_thr"]]], "alternativas": [[["ent_thr"]], [["trait"]]]}
        out = validate(Output.of(state.value, families.get(state.value, [])))
        for b, budget in itertools.product((Backing(True, True), Backing(False, False), None), (4, 64)):
            got = score_cell(cell, out, backing_=b, F_star=F1, W_lo=frozenset({F1, F2}), W_hi=frozenset({F1, F2}),
                             F_adm=F1, necessity=6, budget=budget)
            assert got in OUTCOMES


def test_output_validation_ex23():
    for case in EXAMPLES["EX-23"]["cases"]:
        out = validate(Output.of(case["state"], case["families"]))
        assert (out.reason != "invalid_output") == case["expected_valid"], case
        if not case["expected_valid"]:
            assert out.state == OutputState.FALHA_DE_EXECUCAO


# --------------------------------------------------------------------- backing on oracle-built truth (EX-10/EX-21)


@pytest.fixture(scope="module")
def ex10_truth():
    p3 = Patch("p3", (JsonEdit(MED, ("Entities", 0, "ICD10CMConcepts", 0, "Score"), 0.66),))
    c = make_contrast("c10", "g", [MED], "cm", V1, V1.with_(ent_thr=0.55, icd_thr=0.65), patches=[p3])
    e = toy.evidence({MED: toy.response([toy.entity(1, 0.58, [("C61", 0.62)])])})
    key = AssocKey(MED, SYSTEM_ICD10CM, f"acm:{toy.MODEL_VERSION}", "C61")
    cells = [CellSpec.of("L2-R", "R-A"), CellSpec.of("L2-R", "R-C"), CellSpec.of("L1", "R-C")]
    return build_truth(Hybrids(c, e, HIER), [("q", key)], partition="dev", scenario_family="F", cells=cells,
                       ident=lambda q, cs: Identification.singleton(q.family, "test"))


@pytest.mark.parametrize("case", EXAMPLES["EX-21"]["cases"], ids=lambda c: c["name"])
def test_backing_ex21(ex10_truth, case):
    q = ex10_truth.query("q")
    assert q.F_star == fam(EXAMPLES["EX-21"]["claimed_family"])
    certs = [Certificate(c["kind"], frozenset(c["subject"]), c["value"]) for c in case["certificates"]]
    cell = CellSpec.of(case["view"], case["capability"])
    b = backing(q, ex10_truth.contrast.D, certs, cell, case["log"])
    assert {"all_true": b.all_true, "covered": b.covered, "discarded": len(b.discarded)} == case["expected"]


def test_score_query_end_to_end(ex10_truth):
    D = ex10_truth.contrast.D
    ok = Output.of("explicacao_verificada", [[["ent_thr"]]], [
        ("final", [], False), ("final", D, True), ("eval", ["ent_thr"], True), ("eval", ["icd_thr"], False),
        ("eval", ["patch:p3"], False), ("eval", ["icd_thr", "patch:p3"], False),
    ])
    log = [["ent_thr"], ["icd_thr"], ["patch:p3"], ["icd_thr", "patch:p3"]]
    s = score_query(ex10_truth, "q", ok, CellSpec.of("L2-R", "R-A"), budget=16, log=log)
    assert (s.cell, s.outcome) == ("identificado", "correto_sustentado")
    s = score_query(ex10_truth, "q", ok, CellSpec.of("L2-R", "R-C"), budget=16)
    assert s.outcome == "indevidamente_exclusivo"  # R-C: every eval is discarded
    assert len(s.backing.discarded) == 4
    s = score_query(ex10_truth, "q", Output.of("orcamento_esgotado"), CellSpec.of("L1", "R-C"), budget=16)
    assert s.outcome == "abstencao_desnecessaria"  # necessity 0 under R-C
    bad = Output.of("explicacao_verificada", [[["ent_thr"]], [["icd_thr"]]])
    assert score_query(ex10_truth, "q", bad, CellSpec.of("L2-R", "R-A"), budget=16).outcome == "falha"
