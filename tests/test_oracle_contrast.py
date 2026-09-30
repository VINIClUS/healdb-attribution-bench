import json

import pytest

from habench.data import splits
from habench.oracle.contrast import Contrast, make_contrast
from habench.pipeline.catalog import V1, V2
from habench.pipeline.evidence import JsonEdit, Patch
from habench.types import SealedError

MED = 900_000_001  # not in the split manifest


def ex07(**kw) -> Contrast:
    p1 = Patch("p1", (JsonEdit(MED, ("Entities", 0, "Score"), 0.62),))
    return make_contrast("c1", "g1", [MED], "who", V1, V1.with_(ent_thr=0.58, icd_thr=0.55), patches=[p1], **kw)


def test_d_is_derived_and_sorted():
    c = ex07()
    assert c.D == ("ent_thr", "icd_thr", "patch:p1")
    assert c.x0["patch:p1"] is False and c.x1["patch:p1"] is True
    assert c.d0 == V1 and "patch:p1" not in c.d1.as_dict()


def test_json_round_trip_and_hash_stable():
    c = ex07()
    back = Contrast.from_json(json.loads(c.canonical()))
    assert back == c
    assert back.content_hash() == c.content_hash()
    assert len(c.content_hash()) == 64
    assert ex07(variants1=["ent_thr"]).content_hash() != c.content_hash()


def test_bundle_counts_as_one_factor():
    c = make_contrast("c2", "g1", [MED], "who", V1, V2, bundles={"V1_TO_V2": V1.diff(V2)})
    assert c.D == ("V1_TO_V2",)
    assert set(c.components("V1_TO_V2")) == set(V1.diff(V2))


def test_variant_only_difference_is_in_d():
    c = make_contrast("c3", "g1", [MED], "who", V1, V1, variants0=["trait"])
    assert c.D == ("trait",)


def test_validation_errors():
    with pytest.raises(ValueError):
        make_contrast("c", "g", [MED], "who", V1, V1, variants0=["sel"])  # sel has no alt
    with pytest.raises(ValueError):
        make_contrast("c", "g", [MED], "xx", V1, V2)
    c = ex07()
    bad = Contrast(c.cid, c.group, c.meds, c.space, c.x0, c.x1, c.d0, c.d1, ("ent_thr",), patches=c.patches)
    with pytest.raises(ValueError):
        bad.validate()
    many = V1.with_(occ="first_upsert", sel="top1", ent_thr=0.7, icd_thr=0.3, trait="v2", map="cm_ungated")
    p = Patch("p", (JsonEdit(MED, ("Entities", 0, "Score"), 0.5),))
    with pytest.raises(ValueError, match="> 6"):
        make_contrast("c", "g", [MED], "who", V1, many, patches=[p])


def test_test_group_is_sealed():
    test_med = splits._manifest()[0]["test"][0]
    with pytest.raises(SealedError):
        make_contrast("c", "g", [test_med], "who", V1, V1.with_(ent_thr=0.55))
