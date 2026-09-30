"""Isolated method runs through `run_isolated` (SPEC 11.2): the method lives in a spawned child behind the audit hook.

Misbehaving methods come from `habench.env.testing_methods` (importable by the child; this module is not: it
imports the broker).
"""

from __future__ import annotations

import importlib.machinery
import secrets
import sys
import types
from dataclasses import replace
from pathlib import Path

import pytest

from habench.env.broker import BrokerEnv
from habench.env.rpc import run_isolated
from habench.methods.b0 import B0
from habench.methods.b3 import B3
from habench.methods.base import Query
from habench.oracle import toy
from habench.oracle.contrast import make_contrast
from habench.pipeline.catalog import V1
from habench.pipeline.evidence import JsonEdit, Patch
from habench.types import SYSTEM_ICD10_WHO, AssocKey, OutputState
from habench.views.layout import BrokerSide, Entry, Manifest, patch_handle

MED = 900_000_001
HIER = toy.hierarchy()
KEY = AssocKey(MED, SYSTEM_ICD10_WHO, HIER.version, "C61")
OTHER = AssocKey(MED, SYSTEM_ICD10_WHO, HIER.version, "E11")
QUERIES = [Query("q1", KEY), Query("q2", OTHER)]
TESTING = "habench.env.testing_methods:"
FALHA = OutputState.FALHA_DE_EXECUCAO


def evidence():
    return toy.evidence({MED: toy.response([toy.entity(1, 0.59, [("C61", 0.9)])])})


def contrast():
    p1 = Patch("p1", (JsonEdit(MED, ("Entities", 0, "Score"), 0.62),))
    return make_contrast("c", "g", [MED], "who", V1, V1.with_(ent_thr=0.58, icd_thr=0.55), patches=[p1],
                         check_sealed=False)


@pytest.fixture
def world(tmp_path):
    view, truth = tmp_path / "view", tmp_path / "truth"
    view.mkdir()
    truth.mkdir()
    (view / "a1.bin").write_bytes(b"hello")
    (view / "a2.bin").write_bytes(b"0123456789")
    entries = (Entry("a1", "acm_response", "x0", "00"), Entry("a2", "trace", "x1", "00"))
    (view / "manifest.json").write_text(Manifest("v1", entries).to_json(), encoding="utf-8")
    token = secrets.token_hex(16)
    (truth / "canary.txt").write_text(token)
    return {"view": view, "truth": truth, "token": token}


def make_env(world, view="L2-R", capability="R-A", budget=None) -> BrokerEnv:
    c = contrast()
    handles = tuple((patch_handle(b"k" * 32, c.cid, p.factor), p.factor) for p in c.patches)
    side = BrokerSide("v1", "dev", c.cid, view, handles)
    return BrokerEnv(side, c, evidence(), HIER, world["view"], capability, budget)


def run(world, method, env=None, *, timeout=120, queries=QUERIES):
    return run_isolated(method, env or make_env(world), queries, view_dir=world["view"],
                        truth_root=world["truth"], timeout=timeout)


def norm(e):
    return replace(e, certificates=frozenset(e.certificates))


@pytest.mark.parametrize("method,cls", [("habench.methods.b0:B0", B0), ("habench.methods.b3:B3", B3)])
def test_isolated_equals_in_process(world, method, cls):
    out = run(world, method)
    local_env = make_env(world)
    local = cls().explain(local_env, QUERIES)
    assert out.error is None
    # B3 orders its evaluations through `sorted(frozenset(...))`, a partial order that follows the string hash
    # seed (differs between processes), so certificates are compared as sets.
    assert {q: norm(e) for q, e in out.explanations.items()} == {q: norm(e) for q, e in local.items()}
    assert out.meter.evaluations == local_env.meter().evaluations
    if cls is B3:
        assert out.meter.evaluations == 8 and out.explanations["q1"].state == OutputState.EXPLICACAO_VERIFICADA
    assert out.child_cpu_seconds > 0 and out.meter.peak_rss > 0
    assert out.meter.cpu_seconds >= out.child_cpu_seconds


def test_import_of_oracle_is_denied(world):
    out = run(world, TESTING + "ImportOracle")
    assert out.error and "habench.oracle" in out.error
    assert set(out.explanations) == {"q1", "q2"}
    for e in out.explanations.values():
        assert e.state == FALHA and e.reason.startswith("method_error:")


def test_truth_canary_is_denied(world, monkeypatch):
    monkeypatch.setenv("HAB_TEST_CANARY", str(world["truth"] / "canary.txt"))
    out = run(world, TESTING + "OpenCanary")
    assert out.error and "PermissionError" in out.error
    assert all(e.state == FALHA and world["token"] not in repr(e) for e in out.explanations.values())


def test_timeout_is_a_failed_execution(world):
    out = run(world, TESTING + "Sleeper", timeout=4)
    assert out.error and "timeout" in out.error
    assert all(e.state == FALHA and "timeout" in e.reason for e in out.explanations.values())


def test_crash_is_a_failed_execution(world):
    out = run(world, TESTING + "Crash")
    assert out.error and "code 3" in out.error
    assert all(e.state == FALHA for e in out.explanations.values())


def test_unknown_method_is_a_failed_execution(world):
    out = run(world, TESTING + "NoSuchClass")
    assert out.error and all(e.state == FALHA for e in out.explanations.values())


def test_missing_query_entry_fails_only_that_query(world):
    out = run(world, TESTING + "Forgetful")
    assert out.explanations["q1"].reason == "report"
    assert out.explanations["q2"].state == FALHA and "no explanation" in out.explanations["q2"].reason


def test_invalid_output_is_validated(world):
    out = run(world, TESTING + "Invalid")
    assert all(e.state == FALHA and e.reason == "invalid_output" for e in out.explanations.values())


def notes(out, qid="q1") -> dict[str, str]:
    return dict(n.split("=", 1) for n in out.explanations[qid].notes)


def test_child_loads_no_forbidden_or_trusted_module(world):
    out = run(world, TESTING + "Report")
    assert out.error is None
    n = notes(out)
    assert n["forbidden"] == "" and n["trusted"] == ""
    assert n["main_file"] == "None"  # spawn started the child with a bare __main__


def test_spawn_does_not_reimport_a_forbidden_main(world, monkeypatch):
    """A parent started as `python -m habench.oracle.x` would make spawn import it in the child before the hook."""
    main = types.ModuleType("__main__")
    main.__spec__ = importlib.machinery.ModuleSpec("habench.oracle.toy", None)
    main.__file__ = str(Path(toy.__file__))
    monkeypatch.setitem(sys.modules, "__main__", main)
    out = run(world, TESTING + "Report")
    assert out.error is None and notes(out)["forbidden"] == ""
    assert sys.modules["__main__"] is main  # restored in the parent


def test_env_errors_cross_the_pipe(world):
    out = run(world, TESTING + "Probe", make_env(world, view="L2-R-A3", budget=1))
    assert out.error is None
    n = notes(out)
    assert n["unknown"] == "ValueError" and n["empty"] == "ok" and n["full"] == "BudgetExhausted"
    assert n["executed_config"] == "Unavailable:not_visible" and n["bad_run"] == "ValueError"
    assert n["artifacts"] == "2" and n["bytes"] == "15" and n["capability"] == "R-A"
    assert n["factors"].startswith("ent_thr,ev:") and "patch:" not in n["factors"]
    assert out.meter.evaluations == 1 and out.meter.bytes_read == 15


def test_rc_refusal_crosses_the_pipe(world):
    out = run(world, TESTING + "Probe", make_env(world, capability="R-C"))
    n = notes(out)
    assert n["empty"] == "Unavailable:no_replay" and n["full"] == "Unavailable:no_replay"
    assert out.meter.evaluations == 0
