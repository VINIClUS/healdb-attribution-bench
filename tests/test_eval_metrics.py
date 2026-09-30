import json
from pathlib import Path

import pytest

from habench.eval.metrics import Cost, QueryRecord, costs, per_class_prf, primary, secondary, set_metrics, stratify

DATA = json.loads((Path(__file__).parent / "data" / "spec_examples.json").read_text(encoding="utf-8"))
EX17 = next(e for e in DATA["examples"] if e["id"] == "EX-17")
F = lambda *s: frozenset(frozenset(x) for x in s)  # noqa: E731


def rec(q: dict, **kw) -> QueryRecord:
    base = dict(method="M", view="L2-R", capability="R-A", budget=16, contrast=q["contrast"], group=q["group"],
                scenario_family=q["family"], origin="real", qid=q["qid"], cell=q["cell"], state=q["state"],
                outcome=q["outcome"])
    base.update(kw)
    return QueryRecord(**base)


def test_ex17_primary_metrics():
    rs = [rec(q) for q in EX17["queries"]]
    got = primary(rs)
    exp = EX17["expected"]
    for name in ("cobertura", "cobertura_bruta", "risco_seletivo", "risco_comprometido", "null_group_rate",
                 "null_false_attributions_per_contrast", "falha_rate", "n_indeterminado", "n_incompleta"):
        assert got[name] == pytest.approx(exp[name]), name
    sec = secondary(rs)
    assert sec["unchanged_coverage"] == pytest.approx(exp["unchanged_coverage"])
    assert sec["unchanged_false_attribution_rate"] == pytest.approx(exp["unchanged_false_attribution_rate"])


def test_stratified_by_origin_and_family():
    rs = [rec(q, origin="semisynthetic" if q["group"] == "g2" else "real") for q in EX17["queries"]]
    s = stratify(rs, by=("origin",))
    assert set(s) == {("real",), ("semisynthetic",)}
    assert s[("semisynthetic",)]["cobertura"] == 0.0  # q5 non-committal, q8 failure
    assert set(stratify(rs, by=("origin", "scenario_family"))) == {("real", "F"), ("real", "N"), ("semisynthetic", "X")}


def test_empty_denominators_are_zero():
    got = primary([])
    assert got["cobertura"] == 0.0 and got["risco_comprometido"] == 0.0


def test_per_class_and_set_metrics():
    q = dict(contrast="c", group="g", family="F", cell="identificado", state="explicacao_verificada")
    rs = [
        rec(dict(q, qid="a", outcome="correto_sustentado"), families=(F(["ent_thr"]),), F_star=F(["ent_thr"])),
        rec(dict(q, qid="b", outcome="errado"), families=(F(["icd_thr"], ["patch:p1"]),),
            F_star=F(["patch:p2"], ["icd_thr"])),
        rec(dict(q, qid="c", state="informacao_insuficiente", outcome="abstencao_desnecessaria"),
            F_star=F(["trait"])),
    ]
    prf = per_class_prf(rs)
    assert prf["ent_thr"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert prf["evidence"]["precision"] == 1.0  # patch:p1 and patch:p2 are both class "evidence"
    assert prf["trait"]["recall"] == 0.0
    sm = set_metrics(rs)
    assert sm["n"] == 2 and sm["exact"] == 0.5
    assert sm["precision"] == pytest.approx((1 + 0.5) / 2) and sm["recall"] == pytest.approx((1 + 0.5) / 2)


def test_stability_and_costs():
    q = dict(contrast="c", group="g", family="F", cell="identificado", qid="a", outcome="errado")
    rs = [rec(dict(q, state="explicacao_verificada"), families=(F(["ent_thr"]),), repetition=0),
          rec(dict(q, state="alternativas"), families=(F(["ent_thr"]), F(["trait"])), repetition=1)]
    assert secondary(rs)["stability"] == 0.0
    c = costs([Cost("M", "L2-R", "R-A", 16, "c1", 4, evaluations=8), Cost("M", "L2-R", "R-A", 16, "c2", 4, evaluations=4)])
    assert c["evaluations_per_contrast"] == 6 and c["evaluations_per_query"] == 1.5
