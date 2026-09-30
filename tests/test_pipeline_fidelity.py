"""GATE 1: the core preset V1 reproduces the historical V1 tables exactly; performance bounds."""

import itertools
import time

import pytest

from habench.pipeline import core, tables_v1
from habench.pipeline.catalog import V1, V1_EXTEND, V2, hybrid

pytestmark = pytest.mark.dumps

FUNNEL_V1 = [
    ("records", 274_010),
    ("map", 265_587),
    ("trait_veto", 259_198),
    ("trait_hyp", 171_713),
    ("scores", 43_194),
    ("trait_required", 43_194),
]
FUNNEL_EXTEND = [
    ("records", 274_010),
    ("map", 274_010),
    ("trait_veto", 267_392),
    ("trait_hyp", 177_839),
    ("scores", 44_233),
    ("trait_required", 44_233),
]
V1_ORDER = ("map", "trait_veto", "trait_hyp", "scores", "trait_required")


@pytest.fixture(scope="module")
def v1():
    from habench.pipeline.evidence import load_evidence
    from habench.pipeline.mapping import load_hierarchy

    t0 = time.perf_counter()
    ev = load_evidence("v1")
    hier = load_hierarchy("v1")
    return ev, hier, time.perf_counter() - t0


def _compare(ours, table):
    from habench.data.store import load_records

    c = tables_v1.compare_rows(ours, load_records("v1", table), ("id_med_disease",), json_columns=())
    assert (c["only_ours"], c["only_theirs"], c["differ"]) == ([], [], []), c["differ"][:5]
    assert c["order_equal"]
    return c


def test_md_equal_dump_all_columns_and_ids(v1):
    ev, hier, _ = v1
    rows = tables_v1.md_rows(ev, hier)
    c = _compare(rows, "hd_medication_disease")
    assert c["n_ours"] == c["n_theirs"] == 43_194
    assert [r["id_med_disease"] for r in rows] == list(range(1, 43_195))


def test_v1_funnel(v1):
    ev, hier, _ = v1
    assert core.funnel(core.evaluate(V1, ev, hier), V1_ORDER) == FUNNEL_V1


def test_extend_equal_dump_inferred_rule(v1):
    """Label: inferred rule (F1 §2.4); the gate removal, id search and first id were fitted to V1 data."""
    ev, hier, _ = v1
    assert core.funnel(core.evaluate(V1_EXTEND, ev, hier), V1_ORDER) == FUNNEL_EXTEND
    rows = tables_v1.extend_rows(ev, hier)
    c = _compare(rows, "hd_medication_disease_extend")
    assert c["n_ours"] == 44_233
    assert (rows[0]["id_med_disease"], rows[-1]["id_med_disease"]) == (23_302, 67_534)


def test_cm_space_presence_equals_md(v1):
    from habench.data.store import load_records

    ev, hier, _ = v1
    res = core.run(V1, ev, hier, core.CM)
    md = load_records("v1", "hd_medication_disease", ["id_medication", "cd_icd_full", "vl_score"])
    assert {(k.med, k.code) for k in res.present} == {(r["id_medication"], r["cd_icd_full"]) for r in md}
    scores = {(r["id_medication"], r["cd_icd_full"]): r["vl_score"] for r in md}
    assert all(res.attrs[k].score == scores[(k.med, k.code)] for k in res.present)
    assert {k.version for k in res.present} == {"acm:3.0.0.20231001"}


def test_documented_hypothetical_rule_does_not_reproduce_md(v1):
    """Code/doc drift (F1 §6 item 2): the header's "HYPOTHETICAL accepted only at <= 0.6" drops md rows
    that V1 stored, so the executed rule is the code's > 0.65 veto, not the documented one."""
    ev, hier, _ = v1
    code = core.run(V1, ev, hier, core.CM).present
    doc = core.run(V1.with_(trait="v1_hyp_le_0.6"), ev, hier, core.CM).present
    print(f"documented rule: {len(doc)} keys, {len(code - doc)} V1 md keys lost")
    assert doc < code
    assert (len(doc), len(code - doc)) == (39_319, 3_875)


def test_hierarchy_version_equal_v1_v2():
    from habench.pipeline.mapping import load_hierarchy

    assert load_hierarchy("v1").version == load_hierarchy("v2").version


def test_full_v1_run_under_60s(v1):
    ev, hier, load_s = v1
    t0 = time.perf_counter()
    fresh = ev.subset(ev.meds)  # re-parsed evidence without cached records
    res = core.run(V1, fresh, hier, core.CM)
    run_s = time.perf_counter() - t0
    print(f"parse+hierarchy {load_s:.1f}s, run {run_s:.1f}s")
    assert len(res.present) == 43_194
    assert load_s + run_s <= 60


def test_64_hybrids_v1_to_v2_under_120s(v1):
    ev, hier, _ = v1
    fresh = ev.subset(ev.meds)
    D = sorted(V1.diff(V2))
    assert len(D) == 6
    t0 = time.perf_counter()
    res = {
        frozenset(S): core.run(hybrid(V1, V2, frozenset(S)), fresh, hier, core.WHO).present
        for r in range(7)
        for S in itertools.combinations(D, r)
    }
    elapsed = time.perf_counter() - t0
    print(f"64 hybrids {elapsed:.1f}s")
    assert len(res) == 64 and elapsed <= 120
    p0, pD = res[frozenset()], res[frozenset(D)]
    # diagnostics of design §0 (draft numbers, re-derived here)
    assert (len(p0), len(pD - p0), len(p0 - pD)) == (34_101, 27_405, 18_284)
