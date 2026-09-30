import csv

import pytest

from habench.data import splits as S
from habench.types import SealedError


def test_allocate_totals_and_caps():
    a = S.allocate(1000, {"a": 5000, "b": 3333, "c": 1667})
    assert sum(a.values()) == 1000 and a == {"a": 500, "b": 333, "c": 167}
    b = S.allocate(10, {"a": 5, "b": 5, "c": 5})
    assert sum(b.values()) == 10 and max(b.values()) - min(b.values()) == 1
    capped = S.allocate(5, {"a": 1, "b": 9}, {"a": 1, "b": 4})
    assert capped == {"a": 1, "b": 4}
    with pytest.raises(ValueError):
        S.allocate(3, {"a": 1, "b": 1}, {"a": 1, "b": 1})


def _toy():
    groups = [(f"g{i:04d}", (i,)) for i in range(1, 2001)]
    groups.append(("gbig", (5000, 5001)))
    strata = {gid: ("A" if int(gid[1:]) % 3 else "B") if gid != "gbig" else "A" for gid, _ in groups}
    return groups, strata


def test_assign_splits_totals_and_determinism():
    groups, strata = _toy()
    rows = S.assign_splits(groups, strata, forced_meds={5001, 7})
    again = S.assign_splits(groups, strata, forced_meds={5001, 7})
    assert rows == again
    count = {p: sum(1 for r in rows if r.partition == p) for p in S.PARTITIONS}
    assert count["cal"] == 200 and count["test"] == 600 and count["dev"] == 202
    forced = {r.group_id for r in rows if r.inclusion_prob == 1.0}
    assert forced == {"gbig", "g0007"}
    assert len({r.group_id for r in rows}) == len(groups)
    for r in rows:
        assert r.partition == "dev" or r.inclusion_prob < 1.0


def test_sealing(tmp_path, monkeypatch):
    m = tmp_path / "split_manifest.csv"
    m.write_text(
        "group_id,partition,medications,n_medications,stratum,inclusion_prob\n"
        "ga,dev,1;2,2,x,1.0\ngb,test,3,1,x,0.5\ngc,reserve,4,1,x,0.5\n"
    )
    monkeypatch.setattr(S, "MANIFEST_PATH", m)
    S._load_manifest.cache_clear()
    try:
        assert S.meds_in("dev") == (1, 2) and S.partition_of_med(4) == "reserve"
        with pytest.raises(SealedError):
            S.meds_in("test")
        with pytest.raises(SealedError):
            S.evidence_for("test")
        with pytest.raises(SealedError):
            S.check_not_sealed([1, 3])
        S.check_not_sealed([1, 2, 4])
    finally:
        S._load_manifest.cache_clear()


@pytest.mark.dumps
def test_committed_csvs_match_fresh_build(tmp_path):
    b = S.build()
    S.write_manifest(tmp_path / "m.csv", b.rows)
    S.write_corpus(tmp_path / "c.csv", b.records)
    assert (tmp_path / "m.csv").read_bytes() == S.MANIFEST_PATH.read_bytes()
    assert (tmp_path / "c.csv").read_bytes() == S.CORPUS_PATH.read_bytes()
    assert b.missing_forced == [] and b.missing_translations == []


@pytest.mark.dumps
def test_partitions_forced_and_disjoint():
    with open(S.MANIFEST_PATH, newline="") as fh:
        rows = list(csv.DictReader(fh))
    seen: dict[int, str] = {}
    for r in rows:
        for m in r["medications"].split(";"):
            assert int(m) not in seen  # no group split, no overlap
            seen[int(m)] = r["partition"]
    assert len(seen) == 7447
    assert all(seen[m] == "dev" for m in S.forced_medications())
    sampled = {p: sum(1 for r in rows if r["partition"] == p and float(r["inclusion_prob"]) < 1.0) for p in S.PARTITIONS}
    assert sampled["dev"] == 200 and sampled["cal"] == 200 and sampled["test"] == 600
    assert sum(len(v) for v in (S.meds_in(p) for p in ("dev", "cal", "reserve"))) + sum(
        int(r["n_medications"]) for r in rows if r["partition"] == "test"
    ) == 7447
