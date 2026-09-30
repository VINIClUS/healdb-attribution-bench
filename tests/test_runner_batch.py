import json
from dataclasses import dataclass, replace

import pytest

from habench.oracle import toy
from habench.oracle.contrast import make_contrast
from habench.pipeline.catalog import V1
from habench.runner.batch import Batch
from habench.types import SYSTEM_ICD10_WHO, AssocKey, SealedError
from habench.views.build import Texts

HIER = toy.hierarchy()
MED = 930_000_001


@dataclass(frozen=True)
class Sc:
    contrast: object
    family: str
    subfamily: str
    queries: tuple
    inclusion: dict
    notes: tuple = ()


def _setup():
    ev = toy.evidence({MED: toy.response([toy.entity(1, 0.58, [("C61", 0.9)])])})
    c = make_contrast("cbatch", "g", [MED], "who", V1, V1.with_(ent_thr=0.55), check_sealed=False)
    key = AssocKey(MED, SYSTEM_ICD10_WHO, HIER.version, "C61")
    sc = Sc(c, "F", "ent_thr", (("q1", key),), {"q1": 1.0})
    return ev, sc


def test_batch_runs_resumes_and_scores_nothing_itself(tmp_path):
    ev, sc = _setup()
    b = Batch("dev", "t", ev, HIER, {MED: Texts("pt", "en", "en")}, data_dir=tmp_path, methods=("m", "b3"))
    counts = b.run([sc])
    assert counts["contrasts"] == 1 and counts["errors"] == 0
    assert counts["cells_run"] + counts["cells_equivalent"] == len(b.cells_for(sc))
    outs = sorted((tmp_path / "runs" / "dev" / "t" / "cbatch").glob("*.json"))
    assert outs
    rec = json.loads(next(p for p in outs if p.name == "L2-M__R-A__b64__m.json").read_text())
    assert rec["explanations"]["q1"]["state"] == "explicacao_verificada"
    assert rec["explanations"]["q1"]["families"] == [[["ent_thr"]]]
    assert (tmp_path / "truth" / "dev" / "contrasts" / "cbatch.json").exists()
    assert not list((tmp_path / "views").rglob("*cbatch*"))  # the cid never names a view file
    before = {p: p.stat().st_mtime_ns for p in outs}
    b.run([sc])  # resume: nothing is recomputed
    assert {p: p.stat().st_mtime_ns for p in outs} == before


def test_stale_truth_is_refused(tmp_path):
    ev, sc = _setup()
    b = Batch("dev", "t", ev, HIER, {MED: Texts("pt", "en", "en")}, data_dir=tmp_path, methods=("b0",))
    b.run([sc])
    changed = make_contrast("cbatch", "g", [MED], "who", V1, V1.with_(ent_thr=0.65), check_sealed=False)
    with pytest.raises(RuntimeError, match="stale truth"):
        b.truth(replace(sc, contrast=changed), [])


def test_test_partition_is_sealed(tmp_path):
    ev, _ = _setup()
    with pytest.raises(SealedError):
        Batch("test", "t", ev, HIER, {}, data_dir=tmp_path)
    assert not (tmp_path / "truth").exists()
