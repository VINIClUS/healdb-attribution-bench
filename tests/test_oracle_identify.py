"""`oracle.identify` against the identification examples of the SPEC (EX-11, EX-12, EX-24)."""

import itertools
import json
from pathlib import Path

import pytest

from habench.oracle import toy
from habench.oracle.contrast import has_alt
from habench.oracle.identify import Context, History, identify
from habench.oracle.truth import CellSpec
from habench.pipeline import catalog
from habench.pipeline.catalog import Config
from habench.types import SYSTEM_ICD10_WHO, SYSTEM_ICD10CM, AssocKey

DATA = json.loads((Path(__file__).parent / "data" / "spec_examples.json").read_text(encoding="utf-8"))
EXAMPLES = {e["id"]: e for e in DATA["examples"]}
PRESETS = {"V1": catalog.V1, "V2": catalog.V2}
MED = 900_000_001
HIER = toy.hierarchy()


def config(spec: dict) -> Config:
    spec = dict(spec)
    base = PRESETS[spec.pop("preset")] if "preset" in spec else Config.of({})
    return base.with_items(spec)


def evidence(resp: dict):
    ents = [toy.entity(e["id"], e["score"], [tuple(c) for c in e["concepts"]], [tuple(t) for t in e["traits"]], e["type"])
            for e in resp["entities"]]
    return toy.evidence({MED: toy.response(ents)})


def histories(ex: dict) -> dict[tuple[int, int, int], History]:
    u = ex["universe"]
    out = {}
    for (i, ev), (j, exe), (k, va) in itertools.product(
        enumerate(u["evidence"]), enumerate(u["executed"]), enumerate(u["variants"])
    ):
        alt0 = frozenset(f for f, v in va["x0"].items() if v == "alt")
        alt1 = frozenset(f for f, v in va["x1"].items() if v == "alt")
        x0, x1 = config(exe["x0"]), config(exe["x1"])
        # the JSON reference normalizes `alt` away on levels without an alt variant (SPEC 4.3)
        alt0 = frozenset(f for f in alt0 if has_alt(f, x0[f]))
        alt1 = frozenset(f for f in alt1 if has_alt(f, x1[f]))
        out[(i, j, k)] = History(evidence(ev), x0, x1, alt0, alt1, label=f"h{i}{j}{k}")
    return out


@pytest.mark.parametrize("eid", ["EX-11", "EX-12", "EX-24"])
def test_identification_matches_spec_examples(eid):
    ex = EXAMPLES[eid]
    hs = histories(ex)
    t = ex["true"]
    true_idx = (t["evidence"], t["executed"], t["variants"])
    excluded = {tuple(x) for x in ex.get("exclude_from_universe", [])}
    universe = [h for idx, h in hs.items() if idx not in excluded]
    system = SYSTEM_ICD10CM if ex["space"] == "CM" else SYSTEM_ICD10_WHO
    version = f"acm:{toy.MODEL_VERSION}" if ex["space"] == "CM" else HIER.version
    key = AssocKey(MED, system, version, ex["query"])
    ctx = Context(HIER, ex["space"].lower(), config(ex["declared"]["x0"]), config(ex["declared"]["x1"]), (MED,))
    for v in ex["views"]:
        view = v["view"]
        cell = CellSpec.of(view, v["capability"])
        ident = identify(hs[true_idx], universe, ctx, cell, key, saturated=true_idx not in excluded)
        want = {frozenset(frozenset(S) for S in F) for F in v["expected_families"]}
        assert ident.W_hi == want, (view, v["capability"])
        assert ident.W_lo == want, (view, v["capability"])
        assert ident.state == v["expected_state"], (view, v["capability"])


def test_witness_that_changes_the_rest_of_the_group_is_not_in_w_lo():
    """EX-12 under L1 with a second key (R50.9) in the group: a witness that also alters R50.9 only reaches W_hi."""
    x0, x1 = catalog.V1, catalog.V1.with_(ent_thr=0.55, icd_thr=0.55)
    r50 = toy.entity(2, 0.9, [("R50.9", 0.9)])

    def hist(es, cs, other, label):
        ents = [toy.entity(1, es, [("C61", cs)])] + ([other] if other else [])
        return History(toy.evidence({MED: toy.response(ents)}), x0, x1, label=label)

    true = hist(0.58, 0.9, r50, "true")
    lifted_ok = hist(0.9, 0.58, r50, "icd")  # same R50.9: lifts
    breaks_rest = hist(0.58, 0.58, None, "both")  # drops R50.9: marginal equal, group observation differs
    ctx = Context(HIER, "who", x0, x1, (MED,))
    key = AssocKey(MED, SYSTEM_ICD10_WHO, HIER.version, "C61")
    ident = identify(true, [lifted_ok, breaks_rest], ctx, CellSpec.of("L1", "R-C"), key, saturated=True)
    F = lambda *s: frozenset(frozenset(x) for x in s)  # noqa: E731
    assert ident.W_hi == {F(["ent_thr"]), F(["icd_thr"]), F(["ent_thr", "icd_thr"])}
    assert ident.W_lo == {F(["ent_thr"]), F(["icd_thr"])}
    assert ident.state == "ambiguo"
