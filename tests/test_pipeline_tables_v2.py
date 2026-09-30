import json

import pytest

from habench.pipeline import mapping
from habench.pipeline import tables_v2 as t
from habench.pipeline.mapping import Hierarchy
from habench.pipeline.tables_v1 import compare_rows


def _concept(code, score=0.5, desc="d"):
    return {"Code": code, "Score": score, "Description": desc}


def _entity(eid, concepts, traits=(), text="x", score=0.9, tp="DX_NAME"):
    e = {
        "Text": text,
        "Type": tp,
        "Category": "MEDICAL_CONDITION",
        "Score": score,
        "BeginOffset": 1,
        "EndOffset": 2,
        "ICD10CMConcepts": concepts,
        "Traits": [{"Name": n, "Score": s} for n, s in traits],
    }
    if eid is not None:
        e["Id"] = eid
    return e


def _resp(*entities):
    return json.dumps({"Entities": list(entities)})


HIER = Hierarchy.from_rows(
    [{"cd_cat": "A01", "id_cat": 1, "id_group": 10}, {"cd_cat": "B02", "id_cat": 2, "id_group": 20}],
    [{"cd_subcat": "A010", "id_subcat": 100, "id_cat": 1}],
)


def _pipeline(responses):
    icd = t.entity_icd_rows(responses)
    tr = t.entity_trait_rows(responses)
    audit = t.cutoff_audit_rows(icd, tr, HIER)
    return icd, tr, audit, t.md_rows(audit, HIER)


def test_duplicate_entity_id_merges_last_wins_and_traits_union():
    raw = _resp(
        _entity(7, [_concept("A01", 0.1)], [("NEGATION", 0.1), ("SIGN", 0.2)], text="first"),
        _entity(7, [_concept("A01", 0.7), _concept("B02")], [("NEGATION", 0.8)], text="second"),
    )
    icd = t.entity_icd_rows([(5, raw)])
    assert [(r["nr_entity_id"], r["cd_icd_full"], r["ds_entity_text"], r["vl_icd_score"]) for r in icd] == [
        (7, "A01", "second", 0.7),
        (7, "B02", "second", 0.5),
    ]
    tr = t.entity_trait_rows([(5, raw)])
    assert [(r["nm_trait"], r["vl_trait_score"]) for r in tr] == [("NEGATION", 0.8), ("SIGN", 0.2)]


def test_missing_id_falls_back_to_position_and_text_default():
    raw = _resp(_entity(None, [_concept("A01")], text=None), _entity(None, [_concept("B02")]))
    icd = t.entity_icd_rows([(1, raw)])
    assert [(r["nr_entity_id"], r["ds_entity_text"]) for r in icd] == [(1, ""), (2, "x")]


def test_traits_independent_of_concepts_and_nameless_skipped():
    raw = json.dumps({"Entities": [_entity(1, [], [("SIGN", 0.3)]) | {"Traits": [{"Score": 0.1}, {"Name": "SIGN", "Score": 0.3}]}]})
    assert t.entity_icd_rows([(1, raw)]) == []
    assert [r["nm_trait"] for r in t.entity_trait_rows([(1, raw)])] == ["SIGN"]


def test_bad_json_and_null_skipped():
    good = _resp(_entity(1, [_concept("A01")]))
    assert [r["id_medication"] for r in t.entity_icd_rows([(1, "{no"), (2, good), (3, None)])] == [2]


def test_top1_tie_by_code_and_score_level():
    raw = _resp(_entity(1, [_concept("B02", 0.5), _concept("A01", 0.5), _concept("A01.0", 0.2)]))
    _, _, audit, md = _pipeline([(1, raw)])
    assert len(audit) == 1
    assert audit[0]["cd_icd10cm_full"] == "A01"
    assert audit[0]["tp_icd10cm_score_level"] == "MEDIUM"
    assert audit[0]["cd_icd10_nodot"] == "A01" and audit[0]["tp_icd10_map"] == "CAT3_FALLBACK"
    assert [(r["cd_icd_full"], r["tp_icd_score"]) for r in md] == [("A01", "MEDIUM")]


def test_no_map_dropped_from_md_but_kept_in_audit():
    raw = _resp(_entity(1, [_concept("Z99.9", 0.9)]))
    _, _, audit, md = _pipeline([(1, raw)])
    assert audit[0]["tp_icd10_map"] == "NO_MAP" and audit[0]["cd_icd10_nodot"] is None
    assert audit[0]["id_icd_group"] is None
    assert md == []


def test_negation_veto_and_flags():
    raw = _resp(
        _entity(1, [_concept("A01", 0.9)], [("NEGATION", 0.4)]),
        _entity(2, [_concept("B02", 0.9)], tp="TEST_NAME"),
        _entity(3, [_concept("B02", 0.9)], score=0.5),
    )
    _, _, audit, md = _pipeline([(1, raw)])
    assert [(a["fl_negation"], a["fl_pass_dx_name"], a["fl_pass_negation"], a["fl_pass_entity_score"], a["fl_pass_all_pre"])
            for a in audit] == [(1, 1, 0, 1, 0), (0, 0, 1, 1, 0), (0, 1, 1, 0, 0)]
    assert md == []


def test_medium_cut_and_dedup_best_row():
    raw = _resp(
        _entity(1, [_concept("A01.0", 0.29)]),
        _entity(2, [_concept("A01.0", 0.3)], score=0.8, traits=[("SIGN", 0.2)]),
        _entity(3, [_concept("A01.1", 0.3)], score=0.95, traits=[("SYMPTOM", 0.9)]),
        _entity(4, [_concept("B02", 0.29)]),
    )
    _, _, audit, md = _pipeline([(1, raw)])
    assert audit[0]["tp_icd10cm_score_level"] == "LOW"
    by = {r["cd_icd_full"]: r for r in md}
    assert set(by) == {"A010", "A01"}  # entity 3 (A01.1) falls back to A01, entities 1 and 4 are LOW
    assert by["A010"]["vl_entity_score"] == 0.8 and by["A010"]["nm_trait_main"] == "SIGN"
    assert by["A010"]["vl_trait_main_score"] == 0.2
    assert by["A01"]["vl_entity_score"] == 0.95 and by["A01"]["id_icd_subcat"] is None
    assert [r["id_med_disease"] for r in md] == [1, 2]


def test_trait_name_misalignment_and_tie_flag():
    raw = _resp(
        _entity(1, [_concept("A01.0", 0.8)], score=0.9),  # best row, no trait
        _entity(2, [_concept("A01.0", 0.7)], score=0.9, traits=[("SIGN", 0.6)]),
    )
    _, _, _, md = _pipeline([(1, raw)])
    (row,) = md
    assert row["nm_trait_main"] == "SIGN"  # GROUP_CONCAT skips the NULL name of the best row
    assert row["vl_trait_main_score"] == 0.0  # COALESCE keeps the best row's slot
    assert row["tie_flag"] is False
    tie = _resp(_entity(1, [_concept("A01.0", 0.8)]), _entity(2, [_concept("A01.0", 0.8)]))
    assert _pipeline([(1, tie)])[3][0]["tie_flag"] is True


def test_audit_trait_main_order_and_zero_score():
    raw = _resp(_entity(1, [_concept("A01", 0.9)], [("SIGN", 0.5), ("HYPOTHETICAL", 0.5), ("X", None)]))
    (a,) = _pipeline([(1, raw)])[2]
    assert (a["nm_trait_main"], a["vl_trait_main_score"]) == ("HYPOTHETICAL", 0.5)
    bare = _pipeline([(1, _resp(_entity(1, [_concept("A01", 0.9)])))])[2][0]
    assert (bare["nm_trait_main"], bare["vl_trait_main_score"], bare["fl_negation"]) == (None, None, 0)


# ------------------------------------------------------------------ dumps

AUDIT_COLS = (
    "id_medication nr_entity_id ds_entity_text tp_entity ds_category vl_entity_score nr_begin_offset nr_end_offset "
    "ds_attributes cd_icd10cm_full cd_icd10cm_nodot ds_icd10cm vl_icd10cm_score tp_icd10cm_score_level fl_negation "
    "nm_trait_main vl_trait_main_score cd_icd10_nodot tp_icd10_map id_icd_group id_icd_cat id_icd_subcat "
    "fl_pass_dx_name fl_pass_negation fl_pass_entity_score fl_pass_all_pre"
).split()


@pytest.fixture(scope="module")
def v2():
    from habench.data.store import load_records

    responses = [
        (r["id_medication"], r["ds_api_response"])
        for r in load_records("v2", "hd_int_med_disease_api_response", ["id_medication", "ds_api_response"])
    ]
    icd = t.entity_icd_rows(responses)
    tr = t.entity_trait_rows(responses)
    hier = mapping.load_hierarchy("v2")
    audit = t.cutoff_audit_rows(icd, tr, hier)
    md = t.md_rows(audit, hier)
    return {"icd": icd, "tr": tr, "audit": audit, "md": md, "hier": hier}


def _summary(c):
    return {k: (len(c[k]) if isinstance(c[k], list) else c[k]) for k in ("n_ours", "n_theirs", "only_ours", "only_theirs", "differ", "order_equal")}


@pytest.mark.dumps
def test_v2_entity_icd_and_trait_equal_dump(v2):
    from habench.data.store import load_records

    ci = compare_rows(v2["icd"], load_records("v2", "hd_int_med_disease_entity_icd"),
                      ("id_medication", "nr_entity_id", "cd_icd_full"))
    ct = compare_rows(v2["tr"], load_records("v2", "hd_int_med_disease_entity_trait"),
                      ("id_medication", "nr_entity_id", "nm_trait"))
    print("icd", _summary(ci), ci["differ"][:5])
    print("trait", _summary(ct), ct["differ"][:5])
    assert (ci["n_ours"], ci["n_theirs"]) == (375_595, 375_595)
    assert (ct["n_ours"], ct["n_theirs"]) == (107_543, 107_543)
    for c in (ci, ct):
        assert c["only_ours"] == [] and c["only_theirs"] == [] and c["differ"] == [] and c["order_equal"]


@pytest.mark.dumps
def test_v2_audit_and_md_equal_dump(v2):
    from habench.data.store import load_records

    theirs_a = [{k: r[k] for k in AUDIT_COLS} for r in load_records("v2", "hd_int_med_disease_cutoff_audit")]
    ca = compare_rows(v2["audit"], theirs_a, ("id_medication", "nr_entity_id"))
    ours_md = [{k: v for k, v in r.items() if k != "tie_flag"} for r in v2["md"]]
    cm = compare_rows(ours_md, load_records("v2", "hd_medication_disease"), ("id_medication", "cd_icd_full"))
    print("audit", _summary(ca), ca["differ"][:8])
    print("md", _summary(cm), cm["differ"][:8])
    assert sum(r["tie_flag"] for r in v2["md"]) == 0  # no group has a non-unique best row (measured)
    assert (ca["n_ours"], ca["n_theirs"]) == (75_119, 75_119)
    assert (cm["n_ours"], cm["n_theirs"]) == (27_861, 27_861)
    assert ca["only_ours"] == [] and ca["only_theirs"] == [] and ca["differ"] == [] and ca["order_equal"]
    assert cm["only_ours"] == [] and cm["only_theirs"] == []
    assert cm["differ"] == [] and cm["order_equal"]


@pytest.mark.dumps
def test_core_v2_preset_agrees_with_md(v2):
    from habench.data.store import load_records
    from habench.pipeline import catalog, core
    from habench.pipeline.evidence import load_evidence

    res = core.run(catalog.V2, load_evidence("v2"), v2["hier"], core.WHO)
    theirs = {(r["id_medication"], r["cd_icd_full"]): r["vl_icd_score"] for r in load_records("v2", "hd_medication_disease")}
    ours = {(k.med, k.code): res.attrs[k].score for k in res.present}
    assert set(ours) == set(theirs), (sorted(set(ours) - set(theirs))[:10], sorted(set(theirs) - set(ours))[:10])
    assert len(ours) == 27_861
    assert [k for k in theirs if ours[k] != theirs[k]] == []
