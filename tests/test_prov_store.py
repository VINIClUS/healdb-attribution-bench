from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

import pytest

from habench.prov.records import Activity, Agent, Entity, Relation, RelationKind, new_id, to_dict
from habench.prov.scrub import REDACTED, scrub_record
from habench.prov.store import ProvStore, TruncatedTail

AKIA = "AKIA" + "Q" * 16
SIGV4 = "AWS4-HMAC-SHA256 Credential=" + AKIA + "/20260101/us-east-1/bedrock/aws4_request"


def _sample() -> list:
    return [
        Agent("g", "software", {"v": 1}),
        Activity("a", "call", "ok", "t0", "t1", endpoint="e", consumption={"inputTokens": 3}),
        Entity("e", "resp", sha256="ff", attrs={"é": "ü"}),
        Relation(RelationKind.USED, "a", "e"),
    ]


def test_round_trip_and_jsonl(tmp_path: Path) -> None:
    store = ProvStore(tmp_path / "deep" / "dir" / "prov.jsonl")
    recs = _sample()
    store.append(*recs[:2])
    store.append(*recs[2:])
    assert store.read() == recs
    assert list(store.iter()) == recs
    lines = store.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    assert [json.loads(x) for x in lines] == [to_dict(r) for r in recs]
    assert "é" in lines[2]  # ensure_ascii=False


def test_missing_file_reads_empty(tmp_path: Path) -> None:
    assert ProvStore(tmp_path / "x.jsonl").read() == []


def _worker(path: str, tag: str, n: int) -> None:
    store = ProvStore(Path(path))
    for i in range(n):
        store.append(Entity(new_id(), "k", attrs={"tag": tag, "i": i, "pad": "x" * 5000}))


def test_concurrent_appenders(tmp_path: Path) -> None:
    path = tmp_path / "p.jsonl"
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=_worker, args=(str(path), t, 40)) for t in ("a", "b")]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
        assert p.exitcode == 0
    recs = ProvStore(path).read()
    assert len(recs) == 80
    assert sorted((r.attrs["tag"], r.attrs["i"]) for r in recs) == sorted(
        (t, i) for t in "ab" for i in range(40)
    )


def test_secrets_never_reach_disk(tmp_path: Path) -> None:
    store = ProvStore(tmp_path / "p.jsonl")
    act = Activity(
        "a", "call", "ok", None, None,
        config={"headers": {"Authorization": SIGV4}, "x": "pass" + "word=" + "hunter22"},
        attrs={"key": AKIA},
    )
    store.append(act)
    raw = store.path.read_bytes()
    assert AKIA.encode() not in raw and b"AWS4-HMAC" not in raw and b"hunter22" not in raw
    (back,) = store.read()
    assert back == scrub_record(act)
    assert back.config["headers"]["Authorization"] == REDACTED


def test_truncated_tail(tmp_path: Path) -> None:
    store = ProvStore(tmp_path / "p.jsonl")
    recs = _sample()
    store.append(*recs)
    with store.path.open("ab") as fh:
        fh.write(b'{"record": "entity", "id": "trunc')
    with pytest.raises(TruncatedTail, match="line 5"):
        store.read()
    assert store.read(tolerate_truncated_tail=True) == recs


def test_corrupt_middle_line_always_raises(tmp_path: Path) -> None:
    path = tmp_path / "p.jsonl"
    path.write_text('not json\n{"record": "agent", "id": "g", "kind": "k", "attrs": {}}\n')
    for flag in (False, True):
        with pytest.raises(ValueError, match="line 1"):
            ProvStore(path).read(tolerate_truncated_tail=flag)
