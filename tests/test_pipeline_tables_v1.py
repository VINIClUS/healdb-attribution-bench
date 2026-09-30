import json
import time

import pytest

from habench.pipeline import tables_v1 as t


def _concept(code, score=0.5, desc="d"):
    return {"Code": code, "Score": score, "Description": desc}


def _entity(text, concepts, traits=(), attrs=None, score=0.9):
    e = {
        "Text": text,
        "Type": "DX_NAME",
        "Category": "MEDICAL_CONDITION",
        "Score": score,
        "BeginOffset": 1,
        "EndOffset": 2,
        "ICD10CMConcepts": concepts,
        "Traits": [{"Name": n, "Score": s} for n, s in traits],
    }
    if attrs is not None:
        e["Attributes"] = attrs
    return e


def _resp(*entities):
    return json.dumps({"Entities": list(entities)})


def test_last_wins_on_duplicate_key_and_trait_union():
    raw = _resp(
        _entity("first", [_concept("A01", 0.1)], [("NEGATION", 0.1), ("SIGN", 0.2)]),
        _entity("second", [_concept("A01", 0.7), _concept("B02")], [("NEGATION", 0.8)]),
    )
    ent = t.entity_rows([(5, raw)])
    assert [(r["cd_icd_full"], r["ds_icd_aggreg"], r["vl_score"]) for r in ent] == [
        ("A01", "second", 0.7),
        ("B02", "second", 0.5),
    ]
    tr = t.trait_rows([(5, raw)])
    assert [(r["cd_icd_full"], r["nm_trait"], r["vl_trait_score"]) for r in tr] == [
        ("A01", "NEGATION", 0.8),
        ("A01", "SIGN", 0.2),
        ("B02", "NEGATION", 0.8),
    ]


def test_entity_without_concepts_stores_nothing():
    raw = _resp(_entity("x", [], [("SIGN", 0.3)]))
    assert t.entity_rows([(1, raw)]) == []
    assert t.trait_rows([(1, raw)]) == []


def test_bad_json_and_null_skipped():
    good = _resp(_entity("x", [_concept("A01")]))
    ent = t.entity_rows([(1, "{not json"), (2, good), (3, None)])
    assert [r["id_medication"] for r in ent] == [2]


def test_attributes_default_and_dump():
    raw = _resp(_entity("x", [_concept("A01")]), _entity("y", [_concept("B01")], attrs=[{"Type": "T", "Score": 0.5}]))
    ent = t.entity_rows([(1, raw)])
    assert ent[0]["ds_attributes"] == "[]"
    assert json.loads(ent[1]["ds_attributes"]) == [{"Type": "T", "Score": 0.5}]


def test_ordering_punctuation_digits_letters_case():
    codes = ["A10", "A1.5", "A1", "A1A", "a09", "A_1", "A1.10", "A01"]
    raw = _resp(_entity("x", [_concept(c) for c in codes]))
    got = [r["cd_icd_full"] for r in t.entity_rows([(1, raw)])]
    assert got == ["A_1", "A01", "a09", "A1", "A1.10", "A1.5", "A10", "A1A"]


def test_order_by_medication_first():
    raw = _resp(_entity("x", [_concept("B")]))
    ent = t.entity_rows([(10, raw), (9, raw)])
    assert [r["id_medication"] for r in ent] == [9, 10]


def test_compare_rows():
    a = [{"k": 1, "v": 0.1, "ds_attributes": '[{"a":1,"b":2}]'}, {"k": 2, "v": 1, "ds_attributes": "[]"}]
    b = [{"k": 2, "v": 1.0, "ds_attributes": "[]"}, {"k": 1, "v": 0.1, "ds_attributes": '[{"b": 2, "a": 1}]'}, {"k": 3}]
    res = t.compare_rows(a, b, ("k",))
    assert res["only_theirs"] == [(3,)] and res["only_ours"] == []
    assert [(d[0], d[1]) for d in res["differ"]] == [((2,), "v")]
    assert not res["order_equal"]
    ok = t.compare_rows(a, list(a), ("k",))
    assert ok["differ"] == [] and ok["order_equal"]


@pytest.mark.dumps
def test_v1_tables_equal_dump():
    from habench.data.store import load_records

    responses = [
        (r["id_medication"], r["ds_api_response"])
        for r in load_records("v1", "hd_int_med_disease_api_response", ["id_medication", "ds_api_response"])
    ]
    t0 = time.perf_counter()
    ours_e = t.entity_rows(responses)
    ours_t = t.trait_rows(responses)
    print(f"rebuild: {time.perf_counter() - t0:.1f}s")
    theirs_e = load_records("v1", "hd_int_med_disease_entity")
    theirs_t = load_records("v1", "hd_int_med_disease_trait")
    t1 = time.perf_counter()
    ce = t.compare_rows(ours_e, theirs_e, ("id_medication", "cd_icd_full"))
    ct = t.compare_rows(ours_t, theirs_t, ("id_medication", "cd_icd_full", "nm_trait"))
    print(f"compare: {time.perf_counter() - t1:.1f}s")
    assert (ce["n_ours"], ce["n_theirs"]) == (274_010, 274_010)
    assert (ct["n_ours"], ct["n_theirs"]) == (469_957, 469_957)
    for c in (ce, ct):
        assert c["only_ours"] == [] and c["only_theirs"] == []
        assert c["differ"] == [], c["differ"][:5]
        assert c["order_equal"]
