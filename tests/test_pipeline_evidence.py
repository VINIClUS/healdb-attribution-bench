"""Evidence: array order, statuses, Id fallback, patches, invariants, level-2 document, collation."""

from __future__ import annotations

import json

import pytest

from habench.pipeline.evidence import (
    STATUS_EMPTY,
    STATUS_FAILED,
    STATUS_MISSING,
    STATUS_OK,
    Evidence,
    JsonEdit,
    Patch,
    apply_edits,
    collation_key,
    validate_response,
)


def ent(eid, es, concepts, traits=(), tp="DX_NAME"):
    d = {
        "Id": eid,
        "Score": es,
        "Type": tp,
        "ICD10CMConcepts": [{"Code": c, "Score": s} for c, s in concepts],
        "Traits": [{"Name": n, "Score": s} for n, s in traits],
    }
    if eid is None:
        del d["Id"]
    return d


def resp(*ents, version="1.0.0") -> str:
    return json.dumps({"Entities": list(ents), "ModelVersion": version, "ResponseMetadata": {"HTTPStatusCode": 200}})


def five(top=0.9):
    return [(f"E11.{i}", top - 0.1 * i) for i in range(5)]


# ---------------------------------------------------------------- order and columns


def test_candidates_follow_array_order():
    text = resp(
        ent(7, 0.9, [("I10", 0.8), ("E11.9", 0.5)]),
        ent(3, 0.8, [("J45.0", 0.7)]),
    )
    ev = Evidence.from_responses([(1, text)])
    assert [ev.codes[i] for i in ev.c_code] == ["I10", "E11.9", "J45.0"]
    assert list(ev.c_rank) == [0, 1, 0]
    assert list(ev.c_ent) == [0, 0, 1]
    assert list(ev.e_eid) == [7, 3]
    assert list(ev.e_pos) == [0, 1]
    assert list(ev.c_cs) == [0.8, 0.5, 0.7]
    assert list(ev.c_es) == [0.9, 0.9, 0.8]


def test_entities_without_concepts_and_empty_codes():
    text = resp(ent(1, 0.9, []), ent(2, 0.9, [("", 0.5), ("I10", 0.4)]))
    ev = Evidence.from_responses([(1, text)])
    assert len(ev.e_med) == 2
    assert [ev.codes[i] for i in ev.c_code] == ["I10"]
    assert list(ev.c_rank) == [1]  # rank keeps the position in the response


def test_traits_kept_in_order_and_nameless_dropped():
    e = ent(1, 0.9, [("I10", 0.8)], traits=[("NEGATION", 0.7), ("DIAGNOSIS", None)])
    e["Traits"].append({"Score": 0.1})
    ev = Evidence.from_responses([(1, resp(e))])
    assert ev.e_traits[0] == (("NEGATION", 0.7), ("DIAGNOSIS", None))


def test_status_and_model_version():
    rows = [(1, resp(ent(1, 0.9, [("I10", 0.8)]), version="v9")), (2, resp()), (3, None), (4, "{not json"), (6, "null")]
    ev = Evidence.from_responses(rows, meds=[1, 2, 3, 4, 5, 6])
    assert [ev.status(m) for m in (1, 2, 3, 4, 5, 6)] == [
        STATUS_OK, STATUS_EMPTY, STATUS_FAILED, STATUS_FAILED, STATUS_MISSING, STATUS_FAILED,
    ]
    assert ev.model_version(1) == "v9"
    assert ev.model_version(3) is None
    assert ev.info[3].raw_sha256 is None
    assert ev.info[4].raw_sha256 is not None
    assert ev.info[5].raw_sha256 is None
    assert ev.meds == (1, 2, 3, 4, 5, 6)


def test_scope_defaults_to_responses():
    ev = Evidence.from_responses([(5, resp()), (2, resp())])
    assert ev.meds == (2, 5)


def test_id_fallback_is_position_plus_one():
    text = resp(ent(None, 0.9, [("I10", 0.8)]), ent(None, 0.9, [("I10", 0.8)]))
    assert list(Evidence.from_responses([(1, text)]).e_eid) == [1, 2]
    mixed = resp(ent(7, 0.9, [("I10", 0.8)]), ent(None, 0.9, [("I10", 0.8)]))
    assert list(Evidence.from_responses([(1, mixed)]).e_eid) == [7, 2]


def test_subset_restricts_and_reapplies_patches():
    p = Patch("p", (JsonEdit(2, ("Entities", 0, "Score"), 0.1),))
    ev = Evidence.from_responses([(1, resp(ent(1, 0.9, [("I10", 0.8)]))), (2, resp(ent(1, 0.9, [("I10", 0.8)])))])
    sub = ev.patched([p]).subset([2])
    assert sub.meds == (2,)
    assert list(sub.c_es) == [0.1]
    with pytest.raises(KeyError):
        ev.subset([99])


# ---------------------------------------------------------------- patches


def _patch_case():
    ev = Evidence.from_responses([(1, resp(ent(1, 0.9, [("I10", 0.59)])))])
    p = Patch("p1", (JsonEdit(1, ("Entities", 0, "ICD10CMConcepts", 0, "Score"), 0.62),))
    return ev, p


def test_patch_factor_and_meds():
    _, p = _patch_case()
    assert p.factor == "patch:p1"
    assert p.meds == frozenset({1})


def test_patched_applies_edit_and_leaves_original():
    ev, p = _patch_case()
    ev2 = ev.patched([p])
    assert list(ev2.c_cs) == [0.62]
    assert list(ev.c_cs) == [0.59]
    assert ev.patches == frozenset()
    assert ev2.patches == frozenset({p})
    assert ev.extraction_doc(1)["Entities"][0]["ICD10CMConcepts"][0]["Score"] == 0.59
    assert ev2.extraction_doc(1)["Entities"][0]["ICD10CMConcepts"][0]["Score"] == 0.62


def test_patched_is_cached_and_idempotent():
    ev, p = _patch_case()
    ev2 = ev.patched([p])
    assert ev.patched([p]) is ev2
    assert ev2.patched([p]) is ev2
    assert ev.patched([]) is ev


def test_patched_stacks_on_base():
    ev, p = _patch_case()
    q = Patch("q", (JsonEdit(1, ("Entities", 0, "Score"), 0.3),))
    ev3 = ev.patched([p]).patched([q])
    assert list(ev3.c_cs) == [0.62]
    assert list(ev3.c_es) == [0.3]
    assert ev3 is ev.patched([p, q])


def test_patched_without_response_raises():
    ev = Evidence.from_responses([(1, None)], meds=[1, 2])
    for med in (1, 2, 99):
        with pytest.raises(ValueError):
            ev.patched([Patch("p", (JsonEdit(med, ("Entities", 0, "Score"), 0.1),))])


def test_apply_edits_does_not_mutate_input():
    doc = {"a": [{"b": 1}]}
    out = apply_edits(doc, [JsonEdit(1, ("a", 0, "b"), {"c": 2})])
    assert doc == {"a": [{"b": 1}]}
    assert out == {"a": [{"b": {"c": 2}}]}


# ---------------------------------------------------------------- invariants


def test_valid_response_has_no_violations():
    doc = json.loads(resp(ent(1, 0.9, five()), ent(2, 0.8, [])))
    assert validate_response(doc) == []


def test_validate_flags_each_violation():
    four = json.loads(resp(ent(1, 0.9, five()[:4])))
    assert any("4 concepts" in p for p in validate_response(four))

    unsorted = json.loads(resp(ent(1, 0.9, [("A", 0.5), ("B", 0.9), ("C", 0.4), ("D", 0.3), ("E", 0.2)])))
    assert any("not sorted" in p for p in validate_response(unsorted))

    tie = json.loads(resp(ent(1, 0.9, [("A", 0.9), ("B", 0.9), ("C", 0.4), ("D", 0.3), ("E", 0.2)])))
    problems = validate_response(tie)
    assert any("tie" in p for p in problems)
    assert not any("not sorted" in p for p in problems)

    repeated = json.loads(resp(ent(1, 0.9, []), ent(1, 0.8, [])))
    assert validate_response(repeated) == ["repeated entity Id"]

    high = json.loads(resp(ent(1, 1.5, [])))
    assert any("outside [0, 1]" in p for p in validate_response(high))
    trait_high = json.loads(resp(ent(1, 0.9, [], traits=[("NEGATION", 1.2)])))
    assert any("outside [0, 1]" in p for p in validate_response(trait_high))


# ---------------------------------------------------------------- level-2 document


def test_extraction_doc_drops_only_transport_metadata():
    ev = Evidence.from_responses([(1, resp(ent(1, 0.9, [("I10", 0.8)]))), (2, None)], meds=[1, 2, 3])
    doc = ev.extraction_doc(1)
    assert set(doc) == {"Entities", "ModelVersion"}
    assert doc["Entities"][0]["Id"] == 1
    assert ev.extraction_doc(2) is None
    assert ev.extraction_doc(3) is None


def test_extraction_doc_of_undecodable_response_is_none():
    ev = Evidence.from_responses([(1, "{not json")])
    assert ev.status(1) == STATUS_FAILED
    assert ev.extraction_doc(1) is None


# ---------------------------------------------------------------- collation


def test_collation_symbol_digit_letter_order():
    assert sorted(["a1", "A", "1", ".", "_"], key=collation_key) == ["_", ".", "1", "A", "a1"]


def test_collation_is_case_insensitive_and_prefix_first():
    assert collation_key("e11") == collation_key("E11")
    assert collation_key("E11") < collation_key("E11.65") < collation_key("E11.9")
    assert collation_key("E11.") < collation_key("E110")  # '.' before digits


def test_collation_rejects_unmodelled_characters():
    with pytest.raises(ValueError):
        collation_key("E11-9")
