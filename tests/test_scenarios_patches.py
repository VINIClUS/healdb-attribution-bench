"""Patch operations and the SPEC 4.5 invariant validators."""

import json
from itertools import combinations

import pytest
from test_scenarios_data import MED, MED2, toy_docs

from habench.oracle.contrast import Contrast, make_contrast
from habench.pipeline.catalog import V1
from habench.pipeline.evidence import JsonEdit, Patch, apply_edits
from habench.scenarios import patches as P


@pytest.fixture
def docs():
    return toy_docs()


def raw(*edits: JsonEdit) -> Patch:
    return Patch(P.patch_id(edits), tuple(edits))


# ---------------------------------------------------------------- one test per invariant


def test_rejects_concept_count_change(docs):
    with pytest.raises(P.PatchError, match="concepts per entity"):
        P.check_patch(docs, raw(JsonEdit(MED, ("Entities", 0, "ICD10CMConcepts"), [{"Code": "C61", "Score": 0.9}])))


def test_rejects_unsorted_concepts(docs):
    with pytest.raises(P.PatchError, match="descending"):
        P.set_concept_score(docs, MED, 1, "E11.65", 0.95)  # second concept above the first (0.80)


def test_rejects_tie_at_the_top(docs):
    with pytest.raises(P.PatchError, match="tie at the top"):
        P.set_concept_score(docs, MED, 1, "E11.65", 0.80)


def test_rejects_scores_outside_unit_interval(docs):
    with pytest.raises(P.PatchError):
        P.set_entity_score(docs, MED, 0, 1.5)
    with pytest.raises(P.PatchError):
        P.set_entity_score(docs, MED, 0, float("nan"))
    with pytest.raises(P.PatchError, match=r"\[0, 1\]"):  # a raw edit bypassing the constructors
        P.check_patch(docs, raw(JsonEdit(MED, ("Entities", 1, "Traits", 0, "Score"), -0.1)))
    with pytest.raises(P.PatchError, match=r"\[0, 1\]"):
        P.check_patch(docs, raw(JsonEdit(MED, ("Entities", 1, "ICD10CMConcepts", 1, "Score"), 1.2)))


def test_rejects_new_duplicate_id_but_tolerates_existing_one(docs):
    with pytest.raises(P.PatchError, match="Id repeated"):
        P.check_patch(docs, raw(JsonEdit(MED, ("Entities", 1, "Id"), 1)))  # 1 already repeats; a third copy is new
    assert docs[MED]["Entities"][0]["Id"] == docs[MED]["Entities"][3]["Id"] == 1  # duplicate exists in the data
    P.set_entity_score(docs, MED, 0, 0.61)  # an edit of an entity with a repeated Id is fine
    with pytest.raises(P.PatchError, match="Id repeated"):
        P.check_patch(docs, raw(JsonEdit(MED, ("Entities", 2, "Id"), 2)))  # Id 2 was unique


def test_rejects_overlapping_targets(docs):
    a = P.set_entity_score(docs, MED, 0, 0.61)
    b = P.set_entity_score(docs, MED, 0, 0.62)
    with pytest.raises(P.PatchError, match="overlapping"):
        P.check_patches(docs, [a, b])
    c1 = P.set_concept_score(docs, MED, 1, "E11.9", 0.85)
    c2 = P.set_concept_score(docs, MED, 1, "E11.65", 0.60)
    with pytest.raises(P.PatchError, match="overlapping"):  # the concept list is one field per entity
        P.check_patches(docs, [c1, c2])
    sw = P.swap_entities(docs, MED, 0, 3)
    with pytest.raises(P.PatchError, match="overlapping"):  # a swap covers every field of both entities
        P.check_patches(docs, [sw, a])
    P.check_patches(docs, [a, P.set_concept_score(docs, MED, 1, "E11.9", 0.85), P.add_trait(docs, MED, 2, "NEGATION", 0.8)])
    P.check_patches(docs, [a, P.set_entity_score(docs, MED2, 0, 0.61)])  # other medication: disjoint


def test_no_op_is_rejected(docs):
    with pytest.raises(P.PatchError, match="nothing"):
        P.set_entity_score(docs, MED, 0, 0.59)


def test_missing_targets_are_rejected(docs):
    with pytest.raises(P.PatchError):
        P.set_entity_score(docs, MED, 99, 0.5)
    with pytest.raises(P.PatchError):
        P.set_entity_score(docs, 12345, 0, 0.5)
    with pytest.raises(P.PatchError):
        P.set_concept_score(docs, MED, 0, "Z99", 0.5)


# ---------------------------------------------------------------- operations


def test_operations_edit_the_expected_fields(docs):
    p = P.set_entity_score(docs, MED, 0, 0.61)
    assert apply_edits(docs[MED], p.edits)["Entities"][0]["Score"] == 0.61
    p = P.set_concept_score(docs, MED, 0, "C61", 0.95)
    assert apply_edits(docs[MED], p.edits)["Entities"][0]["ICD10CMConcepts"][0]["Score"] == 0.95
    p = P.add_trait(docs, MED, 0, "NEGATION", 0.8)
    assert {"Name": "NEGATION", "Score": 0.8} in apply_edits(docs[MED], p.edits)["Entities"][0]["Traits"]
    p = P.remove_trait(docs, MED, 0, "DIAGNOSIS")
    assert apply_edits(docs[MED], p.edits)["Entities"][0]["Traits"] == []
    with pytest.raises(P.PatchError):
        P.add_trait(docs, MED, 0, "DIAGNOSIS", 0.5)  # already present
    with pytest.raises(P.PatchError):
        P.remove_trait(docs, MED, 0, "NEGATION")  # absent


def test_swap_exchanges_positions_and_keeps_the_rest(docs):
    p = P.swap_entities(docs, MED, 0, 3)
    out = apply_edits(docs[MED], p.edits)["Entities"]
    assert out[0] == docs[MED]["Entities"][3] and out[3] == docs[MED]["Entities"][0]
    assert out[1:3] == docs[MED]["Entities"][1:3]
    assert P.swap_entities(docs, MED, 3, 0).id == p.id  # order of the arguments is irrelevant
    with pytest.raises(P.PatchError):
        P.swap_entities(docs, MED, 2, 2)


def test_every_subset_of_disjoint_patches_is_valid(docs):
    ps = [
        P.set_entity_score(docs, MED, 0, 0.61),
        P.set_concept_score(docs, MED, 1, "E11.9", 0.85),
        P.add_trait(docs, MED, 2, "NEGATION", 0.8),
        P.swap_entities(docs, MED, 4, 5),
    ]
    P.check_patches(docs, ps)
    for r in range(len(ps) + 1):
        for sub in combinations(ps, r):
            edits = [e for p in sub for e in p.edits]
            out = apply_edits(docs[MED], edits)
            assert P.violations(docs[MED], out) == []
            # application order does not matter for disjoint targets
            assert apply_edits(docs[MED], list(reversed(edits))) == out


def test_ids_are_opaque_and_content_addressed(docs):
    p = P.set_entity_score(docs, MED, 0, 0.61)
    assert p.id.startswith("p") and len(p.id) == 11 and p.id == p.id.lower()
    assert P.set_entity_score(docs, MED, 0, 0.61).id == p.id
    assert P.set_entity_score(docs, MED, 0, 0.62).id != p.id
    for word in ("score", "border", "swap", "ent_thr", "trait"):
        assert word not in p.id


def test_patches_with_list_and_dict_values_are_hashable_and_survive_a_json_round_trip(docs):
    # Evidence.patched hashes Patch objects; plain lists/dicts in JsonEdit.value do not hash
    plist = P.add_trait(docs, MED, 0, "NEGATION", 0.8)
    pdict = P.swap_entities(docs, MED, 4, 5)
    hash(plist), hash(pdict)
    c = make_contrast("c", "g", [MED], "who", V1, V1.with_(ent_thr=0.55), patches=[plist, pdict])
    back = Contrast.from_json(json.loads(c.canonical()))
    assert back.canonical() == c.canonical()
    plain = [p for p in back.patches if p.id == plist.id][0]
    with pytest.raises(TypeError):
        hash(plain)  # plain lists after from_json: the runner re-freezes them
    assert P.freeze_patch(plain) == plain
    hash(P.freeze_patch(plain))
