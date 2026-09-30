import hashlib
import json
import re

import pytest

from habench.methods.base import PresenceMap
from habench.oracle import toy
from habench.oracle.contrast import make_contrast
from habench.oracle.hybrids import Hybrids
from habench.pipeline.catalog import V1
from habench.pipeline.evidence import JsonEdit, Patch
from habench.types import SealedError
from habench.views.build import Texts, build_view
from habench.views.isolation import scan_leaks
from habench.views.layout import CONSTANT_MTIME, BrokerSide, broker_side_path, patch_handle, read_manifest
from habench.views.profiles import kinds

M1, M2, M3 = 900_000_001, 900_000_002, 900_000_003
HIER = toy.hierarchy()
KEY = b"k" * 32
KEY2 = b"z" * 32
CID = "cidQZ7"
PID = "pQZ9"
FAMILY = "famQZ"
VIEWS = ["L1", "L2-R", "L2-M", "L3-M", "L2-R-A1", "L2-R-A2", "L2-R-A3", "L2-R-A4", "L2-R-A5", "L2-M-A6",
         "L2-M-A2", "L2-R-C1", "L2-M-C2", "L2-R-C3", "L2-R-C4", "N1", "N2"]


def evidence():
    r1 = toy.response([toy.entity(1, 0.59, [("C61", 0.9), ("E119", 0.4)]),
                       toy.entity(2, 0.9, [("J450", 0.8), ("R509", 0.3)])])
    r2 = toy.response([toy.entity(1, 0.7, [("E119", 0.9)])])
    return toy.evidence({M1: r1, M2: r2, M3: None})


def contrast(patch=True):
    p = Patch(PID, (JsonEdit(M1, ("Entities", 0, "Score"), 0.62),))
    return make_contrast(CID, "g", [M1, M2, M3], "who", V1, V1.with_(ent_thr=0.58, icd_thr=0.55),
                         patches=[p] if patch else [], check_sealed=False)


TEXTS = {m: Texts(f"fonte {m} é", f"source {m}", f"submitted {m}") for m in (M1, M2, M3)}


def build(view, tmp_path, *, key=KEY, c=None, partition="dev"):
    return build_view(c or contrast(), view, evidence=evidence(), hier=HIER, texts=TEXTS, partition=partition,
                      key=key, data_dir=tmp_path)


def files(view_dir):
    m = read_manifest(view_dir)
    return {(e.kind, e.run): (view_dir / e.file).read_bytes() for e in m.entries}


def test_byte_for_byte_chain(tmp_path):
    f = {v: files(build(v, tmp_path)[0]) for v in ("L1", "L2-R", "L2-M")}
    assert set(f["L1"]) < set(f["L2-R"]) < set(f["L2-M"])
    for small, big in (("L1", "L2-R"), ("L2-R", "L2-M")):
        for k, data in f[small].items():
            assert f[big][k] == data
    assert {k for k, _ in f["L2-M"]} == kinds("L2-M")


def test_ablations_remove_one_and_share_bytes(tmp_path):
    for base in ("L2-R", "L2-M"):
        fb = files(build(base, tmp_path)[0])
        for a, rem, add in (("A1", "submitted_text", None), ("A2", "acm_response", "acm_response_top1"),
                            ("A3", "code_link", None), ("A4", "env_versions", None), ("A5", "ops_actions", None),
                            ("A6", "trace", "trace_winners")):
            if a == "A6" and base == "L2-R":
                continue
            fa = files(build(f"{base}-{a}", tmp_path)[0])
            kb, ka = {k for k, _ in fb}, {k for k, _ in fa}
            assert ka == (kb - {rem}) | ({add} if add else set())
            for k, data in fa.items():
                if k[0] != add:
                    assert fb[k] == data


def test_all_views_build_with_declared_kinds(tmp_path):
    for v in VIEWS:
        d, _ = build(v, tmp_path)
        assert {e.kind for e in read_manifest(d).entries} == kinds(v)


def test_manifest_hashes_layout_and_mtimes(tmp_path):
    d, side = build("L2-M", tmp_path)
    st = d.stat()  # before reading anything: reads move atimes
    assert int(st.st_mtime) == int(st.st_atime) == CONSTANT_MTIME
    m = read_manifest(d)
    assert m.vid == side.vid == d.name
    for e in m.entries:
        assert hashlib.sha256((d / e.file).read_bytes()).hexdigest() == e.sha256
        assert re.fullmatch(r"a[0-9a-f]{12}\.bin", e.file)
    assert sorted(p.name for p in d.iterdir()) == sorted([e.file for e in m.entries] + ["manifest.json"])
    for p in d.iterdir():
        assert int(p.stat().st_mtime) == CONSTANT_MTIME
    order = [e.kind for e in m.entries]
    assert order != sorted(order)
    fl = files(d)
    for run in ("x0", "x1"):
        h = json.loads(fl[("hashes", run)])
        assert set(h) == {"submitted_text", "translation_en", "acm_response", "final"}
        for k, v in h.items():
            assert hashlib.sha256(fl[(k, run)]).hexdigest() == v


def test_hashes_cover_hidden_artifacts(tmp_path):
    fl1 = files(build("L1", tmp_path)[0])
    flm = files(build("L2-M", tmp_path)[0])
    assert fl1[("hashes", "x1")] == flm[("hashes", "x1")]
    h = json.loads(fl1[("hashes", "x0")])
    assert h["acm_response"] == hashlib.sha256(flm[("acm_response", "x0")]).hexdigest()


def test_idempotent_and_deterministic(tmp_path):
    d, _ = build("L2-M", tmp_path)
    m1, f1 = (d / "manifest.json").read_bytes(), files(d)
    (d / "stray.bin").write_bytes(b"x")
    d2, _ = build("L2-M", tmp_path)
    assert d2 == d and (d / "manifest.json").read_bytes() == m1 and files(d) == f1
    assert not (d / "stray.bin").exists()
    d3, _ = build("L2-M", tmp_path / "other")
    assert (d3 / "manifest.json").read_bytes() == m1


def test_unlinkability(tmp_path):
    d1, _ = build("L2-R", tmp_path, key=KEY)
    d2, _ = build("L2-R", tmp_path, key=KEY2)
    assert d1.name != d2.name
    r1 = {(e.kind, e.run): e.ref for e in read_manifest(d1).entries}
    r2 = {(e.kind, e.run): e.ref for e in read_manifest(d2).entries}
    assert not set(r1.values()) & set(r2.values())
    d3, _ = build("L2-M", tmp_path, key=KEY)
    r3 = {(e.kind, e.run): e.ref for e in read_manifest(d3).entries}
    assert all(r1[k] != r3[k] for k in r1)


@pytest.mark.parametrize("view", VIEWS)
def test_no_leaks(tmp_path, view):
    d, _ = build(view, tmp_path)
    assert scan_leaks(d, [CID, "patch:", PID, view, FAMILY, "seed"]) == []
    assert scan_leaks(d, [patch_handle(KEY, CID, f"patch:{PID}")]) == []


def test_final_matches_hybrids_and_lists_unavailable(tmp_path):
    c = contrast()
    fl = files(build("L2-R", tmp_path, c=c)[0])
    h = Hybrids(c, evidence(), HIER)
    for run, S in (("x0", frozenset()), ("x1", frozenset(c.D))):
        pm = PresenceMap.from_json(json.loads(fl[("final", run)]))
        assert pm.present == h.run(S).present
        assert pm.unavailable == {M3}
    assert fl[("final", "x0")] != fl[("final", "x1")]


def test_x1_responses_carry_the_patch_and_top1(tmp_path):
    fl = files(build("L2-R-A2", tmp_path)[0])
    flf = files(build("L2-R", tmp_path)[0])
    x0, x1 = (json.loads(flf[("acm_response", r)]) for r in ("x0", "x1"))
    assert json.loads(x0[str(M1)])["Entities"][0]["Score"] == 0.59
    assert json.loads(x1[str(M1)])["Entities"][0]["Score"] == 0.62
    assert x0[str(M2)] == x1[str(M2)] and x0[str(M3)] is None and x1[str(M3)] is None
    top = json.loads(fl[("acm_response_top1", "x1")])
    for med in (M1, M2):
        for ent in json.loads(top[str(med)])["Entities"]:
            assert len(ent["ICD10CMConcepts"]) == 1
    assert json.loads(top[str(M1)])["Entities"][0]["Score"] == 0.62


def test_config_code_link_and_constants(tmp_path):
    fl = files(build("L2-R", tmp_path)[0])
    assert json.loads(fl[("config_declared", "x1")])["config"]["ent_thr"] == "0.58"
    assert json.loads(fl[("code_link", "x0")])["executed"]["ent_thr"] == "0.6"
    assert "patch:" not in fl[("code_link", "x1")].decode()
    assert json.loads(fl[("env_versions", "")])["hierarchy"] == HIER.version
    assert json.loads(fl[("ops_actions", "")]) == {"actions": []}
    assert json.loads(fl[("source_pt", "")])[str(M1)] == f"fonte {M1} é"


def test_trace_and_winners(tmp_path):
    fl = files(build("L2-M", tmp_path)[0])
    tr = json.loads(fl[("trace", "x0")])
    assert set(tr) == {"candidates", "records", "decisions"} and tr["records"] and tr["decisions"]
    assert tr["records"][0]["key"] is None or len(tr["records"][0]["key"]) == 4
    flw = files(build("L2-M-A6", tmp_path)[0])
    for run in ("x0", "x1"):
        w = json.loads(flw[("trace_winners", run)])
        full = json.loads(fl[("trace", run)])
        approved = {r for r in {d["ref"] for d in full["decisions"]}
                    if all(d["verdict"] for d in full["decisions"] if d["ref"] == r)}
        assert {x["record"]["rid"] for x in w} == approved
        for x in w:
            assert all(d["verdict"] for d in x["decisions"])
            assert "members" not in x["record"]


def test_broker_side_is_under_truth(tmp_path):
    _, side = build("L2-R", tmp_path)
    p = broker_side_path("dev", side.vid, tmp_path)
    assert p.is_relative_to(tmp_path / "truth") and not p.is_relative_to(tmp_path / "views")
    assert BrokerSide.from_json(p.read_text()) == side
    assert side.cid == CID and side.view == "L2-R"
    assert side.handles == ((patch_handle(KEY, CID, f"patch:{PID}"), f"patch:{PID}"),)
    _, noside = build("L2-R", tmp_path, c=contrast(patch=False))
    assert noside.handles == ()


def test_test_partition_is_sealed(tmp_path):
    with pytest.raises(SealedError):
        build("L2-R", tmp_path, partition="test")
    assert list(tmp_path.iterdir()) == []


def test_invalid_view_creates_nothing(tmp_path):
    with pytest.raises(ValueError):
        build("L1-A1", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_n1_n2_contents(tmp_path):
    for v, schema in (("N1", "md_v1"), ("N2", "md_v2")):
        fl = files(build(v, tmp_path)[0])
        assert json.loads(fl[("final", "x0")])["schema"] == schema
        tr = json.loads(fl[("trace", "x1")])
        assert set(tr) == ({"entity", "trait"} if v == "N1" else {"entity_icd", "entity_trait", "cutoff_audit"})
    assert ("submitted_text", "x0") in files(build("N2", tmp_path)[0])
    assert ("submitted_text", "x0") not in files(build("N1", tmp_path)[0])
