"""Adversarial tests of habench.campaign.runner: money, retries, resume, provenance, raw storage, locking."""

import dataclasses
import fcntl
import json
import math
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from test_campaign_fixtures import manifest_path
import yaml

from habench.campaign.acm import AcmOutcome
from habench.campaign.calls import (Condition, Role, Schedule, ScheduledCall, Service, acm_cost_usd, pipeline_acm_text,
                                    sha256_text, translate_cost_usd, translate_worst_case_usd, translation_prompt)
from habench.campaign.money import Ledger
from habench.campaign.plan import Plan, PlanError, Profile, plan_from_dict
from habench.campaign.runner import KIND_ACM, KIND_BLOCK, KIND_ORPHAN, KIND_SKIP, KIND_TRANSLATE, Backends, RunError, Runner
from habench.campaign.schedule import plan_pilot, plan_smoke, read_manifest
from habench.campaign.texts import DictTextSource
from habench.campaign.translate import TranslationOutcome
from habench.prov.export import to_prov_json
from habench.prov.records import Activity, Entity, Relation, RelationKind, validate
from habench.prov.store import ProvStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = manifest_path()
COMM, OPEN = "fake/commercial-v1", "fake/open-v1"
ACM_UNIT = 0.0005


def make_plan(**over: Any) -> Plan:
    d = yaml.safe_load((ROOT / "repro" / "campaign_plan.template.yaml").read_text(encoding="utf-8"))
    for p in d["profiles"]:
        p["model_id"] = OPEN if p["name"] == "open_weights" else COMM
    d["token_prices"] = {COMM: {"input_usd_per_mtok": 3.0, "output_usd_per_mtok": 15.0},
                         OPEN: {"input_usd_per_mtok": 0.5, "output_usd_per_mtok": 1.5}}
    plan = plan_from_dict(d)
    return dataclasses.replace(plan, **over) if over else plan


# ------------------------------------------------------------------ fake services

def acm_ok(text: str, *, raw: bytes | None = b'{"Entities": []}', response: dict | None = None) -> AcmOutcome:
    return AcmOutcome(ok=True, started="2026-01-01T00:00:00.000000Z", ended="2026-01-01T00:00:01.000000Z",
                      latency_ms=1000.0, region="us-east-2", endpoint="https://fake.invalid", input_chars=len(text),
                      raw_body=raw, response={"Entities": [], "ModelVersion": "0.1.0"} if response is None else response,
                      model_version="0.1.0", request_id="req-1", http_date="Thu, 01 Jan 2026 00:00:00 GMT",
                      http_status=200, error_type=None, error_code=None, error_message=None)


def acm_fail(text: str, code: str = "ThrottlingException", *, raw: bytes | None = None,
             message: str = "slow down") -> AcmOutcome:
    return AcmOutcome(ok=False, started="2026-01-01T00:00:00.000000Z", ended="2026-01-01T00:00:01.000000Z",
                      latency_ms=10.0, region="us-east-2", endpoint="https://fake.invalid", input_chars=len(text),
                      raw_body=raw, response=None, model_version=None, request_id="req-f", http_date=None,
                      http_status=400, error_type="ClientError", error_code=code, error_message=message)


def tr_ok(profile: Profile, prompt: str, *, output: str = "Translated text.", input_tokens: int | None = 40,
          output_tokens: int | None = 10, raw: bytes | None = b'{"output": "x"}',
          response: dict | None = None) -> TranslationOutcome:
    return TranslationOutcome(
        ok=True, started="2026-01-01T00:00:00.000000Z", ended="2026-01-01T00:00:01.000000Z", latency_ms=500.0,
        region="us-east-2", endpoint="https://fake.invalid", model_id=profile.model_id,
        temperature=profile.temperature, max_tokens=4096, prompt_sha256=sha256_text(prompt), raw_body=raw,
        response={"output": {"text": output}} if response is None else response, output_text=output,
        stop_reason="end_turn", input_tokens=input_tokens, output_tokens=output_tokens, service_latency_ms=400,
        request_id="req-t", http_date=None, http_status=200, error_type=None, error_code=None, error_message=None)


def tr_fail(profile: Profile, prompt: str, code: str = "ThrottlingException") -> TranslationOutcome:
    return TranslationOutcome(
        ok=False, started="2026-01-01T00:00:00.000000Z", ended="2026-01-01T00:00:01.000000Z", latency_ms=5.0,
        region="us-east-2", endpoint="https://fake.invalid", model_id=profile.model_id,
        temperature=profile.temperature, max_tokens=4096, prompt_sha256=sha256_text(prompt), raw_body=None,
        response=None, output_text=None, stop_reason=None, input_tokens=None, output_tokens=None,
        service_latency_ms=None, request_id="req-tf", http_date=None, http_status=429, error_type="ClientError",
        error_code=code, error_message="too many")


class Fakes:
    """Scriptable backends. acm_fn(n, text) / tr_fn(n, profile, prompt), n = 0-based per-service call index."""

    def __init__(self, acm_fn: Callable[[int, str], AcmOutcome] | None = None,
                 tr_fn: Callable[[int, Profile, str], TranslationOutcome] | None = None) -> None:
        self.acm_fn = acm_fn or (lambda n, text: acm_ok(text))
        self.tr_fn = tr_fn or (lambda n, profile, prompt: tr_ok(profile, prompt))
        self.acm_texts: list[str] = []
        self.tr_calls: list[tuple[str, str, int]] = []

    def _acm(self, text: str) -> AcmOutcome:
        n = len(self.acm_texts)
        self.acm_texts.append(text)
        return self.acm_fn(n, text)

    def _tr(self, profile: Profile, prompt: str, max_tokens: int) -> TranslationOutcome:
        n = len(self.tr_calls)
        self.tr_calls.append((profile.name, prompt, max_tokens))
        return self.tr_fn(n, profile, prompt)

    @property
    def backends(self) -> Backends:
        return Backends(acm=self._acm, translate=self._tr)

    @property
    def n_calls(self) -> int:
        return len(self.acm_texts) + len(self.tr_calls)


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.now += s


# ------------------------------------------------------------------ schedule builders

def acm_call(i: int, *, text: str | None = None, block: int = 0) -> ScheduledCall:
    text = text if text is not None else f"acm input number {i:03d} " + "x" * 40
    return ScheduledCall(call_id=f"acm{i}", block=block, order=i, service=Service.ACM, condition=Condition.SMOKE,
                         role=Role.SMOKE, group_id="g", medication=i, repetition=0, profile=None, input_text=text,
                         input_sha256=sha256_text(text), parent=None)


def tr_call(i: int, *, profile: str = "commercial", text: str | None = None, block: int = 0) -> ScheduledCall:
    text = text if text is not None else f"indicação em português {i}"
    return ScheduledCall(call_id=f"tr{i}", block=block, order=i, service=Service.TRANSLATE,
                         condition=Condition.TRANSLATION_ISOLATED, role=Role.REFERENCE, group_id="g",
                         medication=i, repetition=0, profile=profile, input_text=text,
                         input_sha256=sha256_text(text), parent=None)


def pipe_call(i: int, parent: ScheduledCall) -> ScheduledCall:
    return dataclasses.replace(parent, call_id=f"pipe{i}", order=parent.order + 1, service=Service.ACM,
                               condition=Condition.FULL_PIPELINE, input_text=None, input_sha256=None,
                               parent=parent.call_id)


def schedule_of(*calls: ScheduledCall, kind: str = "smoke") -> Schedule:
    ordered = tuple(dataclasses.replace(c, order=i) for i, c in enumerate(calls))
    return Schedule(kind, 1, "p" * 64, "m" * 64, ordered, ())


def make_runner(tmp_path: Path, schedule: Schedule, fakes: Fakes | None, *, plan: Plan | None = None,
                budget: float = 100.0, clock: Clock | None = None, run_id: str = "run1",
                ledger: Ledger | None = None) -> Runner:
    clock = clock or Clock()
    return Runner(schedule, plan or make_plan(), run_dir=tmp_path / "run", run_id=run_id,
                  ledger=ledger or Ledger(tmp_path / "ledger.jsonl"), backends=None if fakes is None else fakes.backends,
                  budget_usd=budget, sleep=clock.sleep, clock=clock.time)


# ------------------------------------------------------------------ record helpers

def prov(tmp_path: Path) -> list[Any]:
    return ProvStore(tmp_path / "run" / "prov.jsonl").read()


def activities(records: list[Any], kind: str | None = None) -> list[Activity]:
    return [r for r in records if isinstance(r, Activity) and (kind is None or r.kind == kind)]


def attempts(records: list[Any]) -> list[Activity]:
    return [a for a in activities(records) if a.kind in (KIND_ACM, KIND_TRANSLATE)]


def relations(records: list[Any], kind: RelationKind) -> list[Relation]:
    return [r for r in records if isinstance(r, Relation) and r.kind is kind]


def entity(records: list[Any], ident: str) -> Entity:
    return next(r for r in records if isinstance(r, Entity) and r.id == ident)


def reserves(ledger: Ledger, call_id: str | None = None) -> list[dict]:
    return [e for e in ledger.entries() if e["type"] == "reserve"
            and (call_id is None or e["meta"].get("call_id") == call_id)]


def reconciles(ledger: Ledger) -> dict[str, dict]:
    return {e["attempt_id"]: e for e in ledger.entries() if e["type"] == "reconcile"}


def fname(activity_id: str) -> str:
    return activity_id.removeprefix("urn:uuid:")


def all_run_bytes(tmp_path: Path) -> list[tuple[Path, bytes]]:
    return [(p, p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file()]


# ================================================================== 1. dry run

def test_dry_run_calls_nothing_writes_nothing(tmp_path: Path) -> None:
    calls = [acm_call(0), tr_call(1), acm_call(2, block=1), tr_call(3, profile="open_weights", block=2)]
    sched = schedule_of(*calls, pipe_call(4, calls[1]))
    clock = Clock()
    runner = make_runner(tmp_path, sched, None, clock=clock)
    result = runner.run()
    assert result.status == "dry_run" and result.stop_reason is None
    assert result.n_planned == 5 and result.n_ok == 0 and result.n_failed == 0
    assert clock.sleeps == []
    assert not (tmp_path / "run").exists()
    assert not (tmp_path / "ledger.jsonl").exists() or (tmp_path / "ledger.jsonl").read_bytes() == b""


def test_dry_run_leaves_existing_ledger_bytes_unchanged(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.reserve(attempt_id="a0", run_id="other", usd=0.01, cap_usd=1.0, run_budget_usd=1.0)
    ledger.reconcile(attempt_id="a0", usd=0.008, basis="price_list_units")
    before = (tmp_path / "ledger.jsonl").read_bytes()
    result = make_runner(tmp_path, schedule_of(*[acm_call(i) for i in range(4)]), None, ledger=ledger).run()
    assert result.status == "dry_run" and result.n_planned == 4
    assert (tmp_path / "ledger.jsonl").read_bytes() == before
    assert not (tmp_path / "run").exists()


def test_dry_run_stops_at_the_call_that_would_exceed_the_cap(tmp_path: Path) -> None:
    sched = schedule_of(*[acm_call(i) for i in range(6)])
    plan = make_plan(cap_usd=ACM_UNIT * 3.5)
    result = make_runner(tmp_path, sched, None, plan=plan).run()
    assert result.status == "dry_run"
    assert result.n_planned == 3 and result.stop_reason
    assert "cap" in result.stop_reason


def test_dry_run_cap_exactly_reached_still_fits(tmp_path: Path) -> None:
    sched = schedule_of(*[acm_call(i) for i in range(4)])
    result = make_runner(tmp_path, sched, None, plan=make_plan(cap_usd=ACM_UNIT * 3)).run()
    assert result.n_planned == 3 and result.stop_reason is not None


def test_dry_run_respects_run_budget(tmp_path: Path) -> None:
    sched = schedule_of(*[acm_call(i) for i in range(6)])
    result = make_runner(tmp_path, sched, None, budget=ACM_UNIT * 2.5).run()
    assert result.n_planned == 2
    assert result.stop_reason and "budget" in result.stop_reason


def test_dry_run_counts_the_existing_ledger_toward_the_cap(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.reserve(attempt_id="a0", run_id="other", usd=0.0, cap_usd=1.0, run_budget_usd=1.0)
    ledger.reconcile(attempt_id="a0", usd=1.0 - ACM_UNIT * 1.5, basis="price_list_units")
    result = make_runner(tmp_path, schedule_of(*[acm_call(i) for i in range(5)]), None,
                         plan=make_plan(cap_usd=1.0), ledger=ledger).run()
    assert result.n_planned == 1 and result.stop_reason


def test_dry_run_full_pipeline_uses_the_acm_limit_as_worst_case(tmp_path: Path) -> None:
    tr = tr_call(0)
    sched = schedule_of(tr, pipe_call(1, tr))
    plan = make_plan()
    tr_worst = translate_worst_case_usd(translation_prompt(tr.input_text or ""), plan.max_tokens,
                                        plan.token_prices[COMM])
    pipe_worst = 100 * ACM_UNIT  # 10,000 characters = 100 units
    fits = make_runner(tmp_path, sched, None, plan=dataclasses.replace(plan, cap_usd=tr_worst + pipe_worst + 1e-6)).run()
    assert fits.n_planned == 2 and fits.stop_reason is None
    tight = make_runner(tmp_path, sched, None, plan=dataclasses.replace(plan, cap_usd=tr_worst + pipe_worst - 1e-3)).run()
    assert tight.n_planned == 1 and tight.stop_reason


def test_dry_run_refuses_unpriced_translation_model(tmp_path: Path) -> None:
    plan = make_plan(token_prices={})
    with pytest.raises(PlanError):
        make_runner(tmp_path, schedule_of(tr_call(0)), None, plan=plan).run()
    assert not (tmp_path / "run").exists()


def test_dry_run_on_generated_smoke_schedule(tmp_path: Path) -> None:
    rows, sha = read_manifest(FIXTURE)
    texts = DictTextSource({101: "submitted 101", 102: "submitted 102"}, {})
    plan = make_plan(smoke_texts=1, smoke_repetitions=3)
    sched = plan_smoke(rows, sha, plan, "p" * 64, texts)
    result = make_runner(tmp_path, sched, None, plan=plan).run()
    assert result.status == "dry_run" and result.n_planned == 3


# ================================================================== 2. paid path, reservations

def test_acm_reservation_is_the_worst_case_of_the_exact_text(tmp_path: Path) -> None:
    texts = ["a" * 100, "b" * 101, "c" * 1, "d" * 999, "e" * 10_000]
    sched = schedule_of(*[acm_call(i, text=t) for i, t in enumerate(texts)])
    fakes = Fakes()
    runner = make_runner(tmp_path, sched, fakes)
    result = runner.run()
    assert result.status == "completed" and result.n_ok == 5
    assert fakes.acm_texts == texts
    res = reserves(runner.ledger)
    assert len(res) == 5
    plan = make_plan()
    for e, t in zip(res, texts):
        assert e["usd"] == pytest.approx(acm_cost_usd(t, plan.acm_price))
        assert e["meta"]["attempt"] == 1
    assert [round(e["usd"] / ACM_UNIT) for e in res] == [1, 2, 1, 10, 100]
    rec = reconciles(runner.ledger)
    assert set(rec) == {e["attempt_id"] for e in res}
    assert all(r["basis"] == "price_list_units" for r in rec.values())
    assert runner.ledger.outstanding() == []


def test_translation_reservation_and_measured_reconciliation(tmp_path: Path) -> None:
    text = "ção " * 50
    plan = make_plan()
    fakes = Fakes(tr_fn=lambda n, p, prompt: tr_ok(p, prompt, input_tokens=70, output_tokens=25))
    runner = make_runner(tmp_path, schedule_of(tr_call(0, text=text, profile="open_weights")), fakes, plan=plan)
    result = runner.run()
    assert result.n_ok == 1
    prompt = translation_prompt(text)
    assert fakes.tr_calls == [("open_weights", prompt, plan.max_tokens)]
    (res,) = reserves(runner.ledger)
    worst = translate_worst_case_usd(prompt, plan.max_tokens, plan.token_prices[OPEN])
    assert res["usd"] == pytest.approx(worst)
    assert len(prompt.encode()) > len(prompt)  # bytes, not characters
    (rec,) = reconciles(runner.ledger).values()
    assert rec["basis"] == "measured_tokens"
    assert rec["usd"] == pytest.approx(translate_cost_usd(70, 25, plan.token_prices[OPEN]))
    assert rec["usd"] < res["usd"]
    assert result.run_spent_usd == pytest.approx(rec["usd"])


def test_translation_input_is_cut_at_6000_characters_in_prompt_and_reservation(tmp_path: Path) -> None:
    text = "x" * 9000
    fakes = Fakes()
    runner = make_runner(tmp_path, schedule_of(tr_call(0, text=text)), fakes)
    runner.run()
    prompt = translation_prompt(text)
    assert fakes.tr_calls[0][1] == prompt and prompt.count("x") == 6000
    assert reserves(runner.ledger)[0]["usd"] == pytest.approx(
        translate_worst_case_usd(prompt, 4096, make_plan().token_prices[COMM]))


def test_translation_ok_without_usage_reconciles_at_worst_case(tmp_path: Path) -> None:
    fakes = Fakes(tr_fn=lambda n, p, prompt: tr_ok(p, prompt, input_tokens=None, output_tokens=None))
    runner = make_runner(tmp_path, schedule_of(tr_call(0)), fakes)
    runner.run()
    (res,), (rec,) = reserves(runner.ledger), reconciles(runner.ledger).values()
    assert rec["usd"] == pytest.approx(res["usd"]) and rec["basis"] != "measured_tokens"


def test_full_pipeline_reservation_is_worst_case_of_the_derived_text(tmp_path: Path) -> None:
    tr = tr_call(0)
    translation = "  Indicated for the treatment of hypertension.\n\n"
    fakes = Fakes(tr_fn=lambda n, p, prompt: tr_ok(p, prompt, output=translation))
    runner = make_runner(tmp_path, schedule_of(tr, pipe_call(1, tr)), fakes)
    result = runner.run()
    assert result.n_ok == 2
    expected = pipeline_acm_text(translation)
    assert fakes.acm_texts == [expected]
    (res,) = reserves(runner.ledger, "pipe1")
    assert res["usd"] == pytest.approx(acm_cost_usd(expected, make_plan().acm_price))
    (rec,) = [r for a, r in reconciles(runner.ledger).items() if a == res["attempt_id"]]
    assert rec["basis"] == "price_list_units"


def test_full_pipeline_text_is_cut_at_10000_and_reserved_accordingly(tmp_path: Path) -> None:
    tr = tr_call(0)
    fakes = Fakes(tr_fn=lambda n, p, prompt: tr_ok(p, prompt, output="y" * 30_000))
    runner = make_runner(tmp_path, schedule_of(tr, pipe_call(1, tr)), fakes)
    runner.run()
    assert len(fakes.acm_texts[0]) == 10_000
    assert reserves(runner.ledger, "pipe1")[0]["usd"] == pytest.approx(100 * ACM_UNIT)


def test_totals_equal_sum_of_reconciliations_and_each_attempt_has_one_record(tmp_path: Path) -> None:
    tr = tr_call(1)
    sched = schedule_of(acm_call(0), tr, pipe_call(2, tr), acm_call(3))
    runner = make_runner(tmp_path, sched, Fakes())
    result = runner.run()
    rec = reconciles(runner.ledger)
    res = reserves(runner.ledger)
    assert len(res) == len(rec) == result.n_attempts == 4
    assert math.isclose(runner.ledger.totals().spent_usd, math.fsum(r["usd"] for r in rec.values()))
    assert result.run_spent_usd == pytest.approx(runner.ledger.totals().spent_usd)
    records = prov(tmp_path)
    assert sorted(a.id for a in attempts(records)) == sorted(e["attempt_id"] for e in res)
    assert validate(records) == []


def test_finished_run_rerun_makes_no_calls_and_no_reservations(tmp_path: Path) -> None:
    sched = schedule_of(acm_call(0), acm_call(1))
    make_runner(tmp_path, sched, Fakes()).run()
    ledger_bytes = (tmp_path / "ledger.jsonl").read_bytes()
    again = Fakes()
    result = make_runner(tmp_path, sched, again).run()
    assert result.status == "completed" and result.n_ok == 2
    assert again.n_calls == 0
    assert (tmp_path / "ledger.jsonl").read_bytes() == ledger_bytes


def test_pilot_schedule_end_to_end_with_fakes(tmp_path: Path) -> None:
    rows, sha = read_manifest(FIXTURE)
    texts = DictTextSource({101: "submitted 101", 102: "submitted 102", 201: "submitted 201"},
                           {101: "indicação um longa", 102: "indicação dois longa", 201: "indicação três longa"})
    plan = make_plan(pilot_texts=2, pilot_repetitions=4, pilot_references=2, pilot_blocks=1)
    sched = plan_pilot(rows, sha, plan, "p" * 64, texts)
    fakes = Fakes(tr_fn=lambda n, p, prompt: tr_ok(p, prompt, output=f"  translated {n} \n"))
    runner = make_runner(tmp_path, sched, fakes, plan=plan)
    result = runner.run()
    assert result.status == "completed" and result.n_ok == len(sched.calls) == result.n_attempts
    records = prov(tmp_path)
    assert validate(records) == []
    by_call = {a.attrs["call_id"]: a for a in attempts(records)}
    assert len(by_call) == len(sched.calls)
    used = {r.subject: r.object for r in relations(records, RelationKind.USED)}
    for c in sched.calls:
        if c.condition is Condition.FULL_PIPELINE:
            child_input = entity(records, used[by_call[c.call_id].id])
            assert child_input.sha256 in {sha256_text(pipeline_acm_text(f"  translated {n} \n"))
                                          for n in range(len(fakes.tr_calls))}
            assert by_call[c.call_id].attrs["role"] == str(c.role)


# ================================================================== 3. cumulative cap and run budget

def prefill(ledger: Ledger, usd: float, run_id: str = "other") -> None:
    ledger.reserve(attempt_id=f"pre-{run_id}", run_id=run_id, usd=usd, cap_usd=1e9, run_budget_usd=1e9)
    ledger.reconcile(attempt_id=f"pre-{run_id}", usd=usd, basis="price_list_units")


def test_cap_reached_stops_without_calling_or_reserving_then_resume_continues(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    prefill(ledger, 0.049)
    sched = schedule_of(*[acm_call(i) for i in range(5)])
    plan = make_plan(cap_usd=0.0501)  # two 1-unit calls fit (0.049 + 0.0005 * 2 = 0.0500)
    first = Fakes()
    r1 = make_runner(tmp_path, sched, first, plan=plan, ledger=ledger).run()
    assert r1.status == "cap_reached" and r1.stop_reason and "cap" in r1.stop_reason
    assert r1.n_ok == 2 and r1.n_attempts == 2
    assert len(first.acm_texts) == 2
    assert len(reserves(ledger, None)) == 3  # prefill + 2; the refused attempt wrote nothing
    assert ledger.outstanding() == []
    assert ledger.totals().spent_usd <= plan.cap_usd + 1e-9

    second = Fakes()
    r2 = make_runner(tmp_path, sched, second, plan=dataclasses.replace(plan, cap_usd=10.0), ledger=ledger).run()
    assert r2.status == "completed" and r2.n_ok == 5 and r2.n_attempts == 5
    done = Counter(first.acm_texts + second.acm_texts)
    assert set(done.values()) == {1} and len(done) == 5
    assert second.acm_texts == [c.input_text for c in sched.calls[2:]]
    assert validate(prov(tmp_path)) == []


def test_cap_already_exhausted_by_another_run_makes_no_call_at_all(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    prefill(ledger, 0.05)
    fakes = Fakes()
    result = make_runner(tmp_path, schedule_of(acm_call(0)), fakes, plan=make_plan(cap_usd=0.05), ledger=ledger).run()
    assert result.status == "cap_reached" and fakes.n_calls == 0 and result.n_attempts == 0
    assert len(reserves(ledger)) == 1


def test_cap_counts_outstanding_reservations_of_other_runs(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.reserve(attempt_id="orphan", run_id="other", usd=0.04, cap_usd=1.0, run_budget_usd=1.0)  # never reconciled
    fakes = Fakes()
    result = make_runner(tmp_path, schedule_of(*[acm_call(i) for i in range(4)]), fakes,
                         plan=make_plan(cap_usd=0.0411), ledger=ledger).run()
    assert result.status == "cap_reached" and len(fakes.acm_texts) == 2


def test_run_budget_stop_then_resume_with_larger_budget(tmp_path: Path) -> None:
    sched = schedule_of(*[acm_call(i) for i in range(5)])
    first = Fakes()
    r1 = make_runner(tmp_path, sched, first, budget=ACM_UNIT * 2.5).run()
    assert r1.status == "cap_reached" and r1.stop_reason and "budget" in r1.stop_reason
    assert len(first.acm_texts) == 2 and r1.run_spent_usd == pytest.approx(2 * ACM_UNIT)
    second = Fakes()
    r2 = make_runner(tmp_path, sched, second, budget=ACM_UNIT * 5.5).run()  # the budget covers the whole run
    assert r2.status == "completed" and len(second.acm_texts) == 3
    assert r2.run_spent_usd == pytest.approx(5 * ACM_UNIT)
    # the resumed run did not repeat any call
    assert sorted(first.acm_texts + second.acm_texts) == sorted(c.input_text for c in sched.calls)


def test_cap_hit_between_retries_leaves_call_unfinished_and_resume_finishes_it(tmp_path: Path) -> None:
    sched = schedule_of(acm_call(0), acm_call(1))
    plan = make_plan(cap_usd=ACM_UNIT * 1.5)
    fakes = Fakes(acm_fn=lambda n, t: acm_fail(t) if n == 0 else acm_ok(t))
    ledger = Ledger(tmp_path / "ledger.jsonl")
    r1 = make_runner(tmp_path, sched, fakes, plan=plan, ledger=ledger).run()
    assert r1.status == "cap_reached" and len(fakes.acm_texts) == 1
    assert r1.n_failed == 0  # not terminally failed: a refused retry is not a failure of the call
    again = Fakes()
    r2 = make_runner(tmp_path, sched, again, plan=make_plan(cap_usd=1.0), ledger=ledger).run()
    assert r2.status == "completed" and r2.n_ok == 2
    (first_reserve, second_reserve) = reserves(ledger, "acm0")
    assert (first_reserve["meta"]["attempt"], second_reserve["meta"]["attempt"]) == (1, 2)


# ================================================================== 4. retries

def test_retryable_error_is_retried_up_to_max_attempts_with_own_records(tmp_path: Path) -> None:
    plan = make_plan()
    fakes = Fakes(acm_fn=lambda n, t: acm_fail(t, "ThrottlingException"))
    clock = Clock()
    runner = make_runner(tmp_path, schedule_of(acm_call(0)), fakes, plan=plan, clock=clock)
    result = runner.run()
    assert plan.retry.max_attempts == 3
    assert len(fakes.acm_texts) == 3
    assert result.status == "completed" and result.n_failed == 1 and result.n_ok == 0 and result.n_attempts == 3
    assert len(clock.sleeps) == 2 and all(s > 0 for s in clock.sleeps) and clock.sleeps == sorted(clock.sleeps)
    res = reserves(runner.ledger)
    assert [e["meta"]["attempt"] for e in res] == [1, 2, 3]
    assert len({e["attempt_id"] for e in res}) == 3
    records = prov(tmp_path)
    acts = attempts(records)
    assert [a.id for a in acts] == [e["attempt_id"] for e in res]
    assert [a.attrs["terminal"] for a in acts] == [None, None, "failed"]
    assert all(a.status == "error" and a.error["code"] == "ThrottlingException" for a in acts)
    retry_links = [(r.subject, r.object) for r in relations(records, RelationKind.WAS_INFORMED_BY)
                   if r.attrs.get("reason") == "retry"]
    assert retry_links == [(acts[1].id, acts[0].id), (acts[2].id, acts[1].id)]
    for e in reconciles(runner.ledger).values():
        assert e["basis"] == "worst_case_failed"
    assert result.run_spent_usd == pytest.approx(3 * ACM_UNIT)  # three failures at the 1-unit worst case


def test_retry_then_success_reconciles_failure_at_worst_case_and_success_at_price(tmp_path: Path) -> None:
    text = "z" * 250  # 3 units
    fakes = Fakes(acm_fn=lambda n, t: acm_fail(t, "ServiceUnavailableException") if n < 2 else acm_ok(t))
    runner = make_runner(tmp_path, schedule_of(acm_call(0, text=text)), fakes)
    result = runner.run()
    assert result.n_ok == 1 and result.n_failed == 0 and result.n_attempts == 3
    res = reserves(runner.ledger)
    rec = reconciles(runner.ledger)
    assert [rec[e["attempt_id"]]["basis"] for e in res] == ["worst_case_failed", "worst_case_failed",
                                                             "price_list_units"]
    assert all(rec[e["attempt_id"]]["usd"] == pytest.approx(3 * ACM_UNIT) for e in res)
    acts = attempts(prov(tmp_path))
    assert [a.status for a in acts] == ["error", "error", "ok"]
    assert acts[-1].attrs["terminal"] == "ok"


def test_non_retryable_error_fails_at_once(tmp_path: Path) -> None:
    fakes = Fakes(acm_fn=lambda n, t: acm_fail(t, "ValidationException"))
    clock = Clock()
    runner = make_runner(tmp_path, schedule_of(acm_call(0), acm_call(1)), fakes, clock=clock)
    result = runner.run()
    assert len(fakes.acm_texts) == 2  # one attempt each; the next call is still tried
    assert result.n_failed == 2 and result.n_attempts == 2 and clock.sleeps == []
    assert [a.attrs["terminal"] for a in attempts(prov(tmp_path))] == ["failed", "failed"]
    assert all(r["basis"] == "worst_case_failed" for r in reconciles(runner.ledger).values())


def test_error_without_a_code_is_not_retried(tmp_path: Path) -> None:
    fakes = Fakes(acm_fn=lambda n, t: acm_fail(t, None))  # type: ignore[arg-type]
    result = make_runner(tmp_path, schedule_of(acm_call(0)), fakes).run()
    assert len(fakes.acm_texts) == 1 and result.n_failed == 1


def test_max_attempts_one_never_retries(tmp_path: Path) -> None:
    plan = make_plan(retry=dataclasses.replace(make_plan().retry, max_attempts=1))
    fakes = Fakes(acm_fn=lambda n, t: acm_fail(t))
    result = make_runner(tmp_path, schedule_of(acm_call(0)), fakes, plan=plan).run()
    assert len(fakes.acm_texts) == 1 and result.n_failed == 1


def test_translation_retry_uses_a_fresh_reservation_each_time(tmp_path: Path) -> None:
    fakes = Fakes(tr_fn=lambda n, p, prompt: tr_fail(p, prompt, "ThrottlingException") if n == 0 else tr_ok(p, prompt))
    runner = make_runner(tmp_path, schedule_of(tr_call(0)), fakes)
    result = runner.run()
    assert result.n_ok == 1 and len(fakes.tr_calls) == 2
    res = reserves(runner.ledger)
    assert len(res) == 2 and res[0]["usd"] == pytest.approx(res[1]["usd"])
    rec = reconciles(runner.ledger)
    assert rec[res[0]["attempt_id"]]["basis"] == "worst_case_failed"
    assert rec[res[0]["attempt_id"]]["usd"] == pytest.approx(res[0]["usd"])
    assert rec[res[1]["attempt_id"]]["basis"] == "measured_tokens"


def test_failure_without_a_body_is_never_recorded_as_an_empty_response(tmp_path: Path) -> None:
    fakes = Fakes(acm_fn=lambda n, t: acm_fail(t, "ValidationException"))
    make_runner(tmp_path, schedule_of(acm_call(0)), fakes).run()
    records = prov(tmp_path)
    assert not [r for r in records if isinstance(r, Entity) and r.kind == "acm_response"]
    assert relations(records, RelationKind.WAS_GENERATED_BY) == []
    (act,) = attempts(records)
    assert act.status == "error" and act.error and act.error["code"] == "ValidationException"
    assert not (tmp_path / "run" / "raw").exists() or list((tmp_path / "run" / "raw").iterdir()) == []


def test_failure_with_a_service_body_keeps_it_verbatim(tmp_path: Path) -> None:
    body = b'{"__type":"ValidationException","message":"bad"}'
    fakes = Fakes(acm_fn=lambda n, t: acm_fail(t, "ValidationException", raw=body))
    make_runner(tmp_path, schedule_of(acm_call(0)), fakes).run()
    (act,) = attempts(prov(tmp_path))
    raws = list((tmp_path / "run" / "raw").iterdir())
    assert [p.read_bytes() for p in raws] == [body]
    assert raws[0].name == f"{fname(act.id)}.body"


def test_failed_response_is_never_marked_ok_in_the_call_state(tmp_path: Path) -> None:
    fakes = Fakes(acm_fn=lambda n, t: acm_fail(t, "ValidationException"))
    result = make_runner(tmp_path, schedule_of(acm_call(0)), fakes).run()
    assert result.n_ok == 0 and result.n_failed == 1


# ================================================================== 5. full pipeline

def test_pipeline_input_derivation_and_provenance_links(tmp_path: Path) -> None:
    tr = tr_call(0)
    translation = "\n  What a translation.  \n"
    fakes = Fakes(tr_fn=lambda n, p, prompt: tr_ok(p, prompt, output=translation))
    make_runner(tmp_path, schedule_of(tr, pipe_call(1, tr)), fakes).run()
    expected = pipeline_acm_text(translation)
    assert fakes.acm_texts == [expected]
    records = prov(tmp_path)
    parent = next(a for a in attempts(records) if a.attrs["call_id"] == "tr0")
    child = next(a for a in attempts(records) if a.attrs["call_id"] == "pipe1")
    parent_output = next(r.subject for r in relations(records, RelationKind.WAS_GENERATED_BY) if r.object == parent.id)
    child_input = next(r.object for r in relations(records, RelationKind.USED) if r.subject == child.id)
    assert (child_input, parent_output) in [(r.subject, r.object)
                                            for r in relations(records, RelationKind.WAS_DERIVED_FROM)]
    informed = [r for r in relations(records, RelationKind.WAS_INFORMED_BY) if r.subject == child.id]
    assert [(r.object, r.attrs.get("reason")) for r in informed] == [(parent.id, "pipeline_input")]
    inp = entity(records, child_input)
    assert inp.sha256 == sha256_text(expected)
    assert (tmp_path / "run" / inp.attrs["file"]).read_text(encoding="utf-8") == expected
    assert validate(records) == []


def test_pipeline_child_after_parent_retry_is_linked_to_the_successful_attempt(tmp_path: Path) -> None:
    tr = tr_call(0)
    fakes = Fakes(tr_fn=lambda n, p, prompt: tr_fail(p, prompt) if n == 0 else tr_ok(p, prompt, output="Second."))
    make_runner(tmp_path, schedule_of(tr, pipe_call(1, tr)), fakes).run()
    records = prov(tmp_path)
    tr_attempts = [a for a in attempts(records) if a.attrs["call_id"] == "tr0"]
    child = next(a for a in attempts(records) if a.attrs["call_id"] == "pipe1")
    assert len(tr_attempts) == 2
    assert fakes.acm_texts == [pipeline_acm_text("Second.")]
    (link,) = [r for r in relations(records, RelationKind.WAS_INFORMED_BY) if r.subject == child.id]
    assert link.object == tr_attempts[1].id
    good_output = next(r.subject for r in relations(records, RelationKind.WAS_GENERATED_BY)
                       if r.object == tr_attempts[1].id)
    child_input = next(r.object for r in relations(records, RelationKind.USED) if r.subject == child.id)
    assert (child_input, good_output) in [(r.subject, r.object)
                                          for r in relations(records, RelationKind.WAS_DERIVED_FROM)]


def test_failed_parent_makes_child_not_executed_without_reservation_or_call(tmp_path: Path) -> None:
    tr = tr_call(0)
    fakes = Fakes(tr_fn=lambda n, p, prompt: tr_fail(p, prompt, "ValidationException"))
    sched = schedule_of(tr, pipe_call(1, tr), acm_call(2))
    runner = make_runner(tmp_path, sched, fakes)
    result = runner.run()
    assert fakes.acm_texts == [sched.calls[2].input_text]  # only the unrelated ACM call ran
    assert result.n_failed == 1 and result.n_not_executed == 1 and result.n_ok == 1
    assert reserves(runner.ledger, "pipe1") == []
    records = prov(tmp_path)
    (skip,) = activities(records, KIND_SKIP)
    assert skip.attrs["call_id"] == "pipe1" and skip.attrs["terminal"] == "not_executed"
    assert skip.status == "not_executed"
    assert not [a for a in attempts(records) if a.attrs["call_id"] == "pipe1"]
    assert validate(records) == []


def test_parent_exhausting_retries_makes_child_not_executed(tmp_path: Path) -> None:
    tr = tr_call(0)
    fakes = Fakes(tr_fn=lambda n, p, prompt: tr_fail(p, prompt, "ThrottlingException"))
    runner = make_runner(tmp_path, schedule_of(tr, pipe_call(1, tr)), fakes)
    result = runner.run()
    assert len(fakes.tr_calls) == 3 and fakes.acm_texts == []
    assert result.n_failed == 1 and result.n_not_executed == 1 and reserves(runner.ledger, "pipe1") == []


def test_not_executed_child_is_not_retried_on_resume(tmp_path: Path) -> None:
    tr = tr_call(0)
    sched = schedule_of(tr, pipe_call(1, tr))
    make_runner(tmp_path, sched, Fakes(tr_fn=lambda n, p, prompt: tr_fail(p, prompt, "ValidationException"))).run()
    again = Fakes()
    result = make_runner(tmp_path, sched, again).run()
    assert again.n_calls == 0 and result.n_not_executed == 1 and result.n_failed == 1
    assert len(activities(prov(tmp_path), KIND_SKIP)) == 1


def test_resume_between_parent_and_child_keeps_exact_input_and_derivation(tmp_path: Path) -> None:
    tr = tr_call(0)
    sched = schedule_of(tr, pipe_call(1, tr))
    translation = " Resumed translation. "

    def crash(n: int, text: str) -> AcmOutcome:
        raise KeyboardInterrupt

    first = Fakes(acm_fn=crash, tr_fn=lambda n, p, prompt: tr_ok(p, prompt, output=translation))
    with pytest.raises(KeyboardInterrupt):
        make_runner(tmp_path, sched, first).run()
    second = Fakes()
    result = make_runner(tmp_path, sched, second).run()
    assert result.n_ok == 2 and second.tr_calls == []
    assert second.acm_texts == [pipeline_acm_text(translation)]
    records = prov(tmp_path)
    child = next(a for a in attempts(records) if a.attrs["call_id"] == "pipe1")
    parent = next(a for a in attempts(records) if a.attrs["call_id"] == "tr0")
    parent_output = next(r.subject for r in relations(records, RelationKind.WAS_GENERATED_BY) if r.object == parent.id)
    child_input = next(r.object for r in relations(records, RelationKind.USED) if r.subject == child.id)
    assert (child_input, parent_output) in [(r.subject, r.object)
                                            for r in relations(records, RelationKind.WAS_DERIVED_FROM)]
    assert child.attrs["attempt"] == 2  # the interrupted attempt counts
    assert validate(records) == []


# ================================================================== 6. crash / resume

def interrupt_on(k: int, then: Callable[[int, str], AcmOutcome] | None = None) -> Callable[[int, str], AcmOutcome]:
    def fn(n: int, text: str) -> AcmOutcome:
        if n == k:
            raise KeyboardInterrupt
        return (then or (lambda _n, t: acm_ok(t)))(n, text)
    return fn


def test_interrupted_attempt_becomes_an_orphan_reconciled_at_worst_case(tmp_path: Path) -> None:
    sched = schedule_of(*[acm_call(i, text="q" * 150) for i in range(4)])  # 2 units each
    first = Fakes(acm_fn=interrupt_on(2))
    ledger = Ledger(tmp_path / "ledger.jsonl")
    with pytest.raises(KeyboardInterrupt):
        make_runner(tmp_path, sched, first, ledger=ledger).run()
    (orphan,) = ledger.outstanding()
    assert orphan["meta"]["call_id"] == "acm2" and len(reserves(ledger)) == 3

    second = Fakes()
    result = make_runner(tmp_path, sched, second, ledger=ledger).run()
    assert result.status == "completed" and result.n_ok == 4
    assert len(second.acm_texts) == 2  # acm2 is redone, acm3 done; acm0/acm1 not repeated
    assert ledger.outstanding() == []
    rec = reconciles(ledger)[orphan["attempt_id"]]
    assert rec["basis"] == "worst_case_orphan" and rec["usd"] == pytest.approx(orphan["usd"])

    records = prov(tmp_path)
    (interrupted,) = activities(records, KIND_ORPHAN)
    assert interrupted.id == orphan["attempt_id"] and interrupted.status == "interrupted"
    assert interrupted.attrs["call_id"] == "acm2"
    redo = next(a for a in attempts(records) if a.attrs["call_id"] == "acm2")
    assert redo.attrs["attempt"] == 2 and redo.id != interrupted.id
    assert len(reserves(ledger, "acm2")) == 2
    assert validate(records) == []
    to_prov_json(records)  # export succeeds
    ids = [r.id for r in records if not isinstance(r, Relation)]
    assert len(ids) == len(set(ids))
    assert ledger.totals().spent_usd == pytest.approx(sum(r["usd"] for r in reconciles(ledger).values()))
    assert result.n_attempts == 5 and result.run_spent_usd == pytest.approx(ledger.totals().spent_usd)


def test_orphan_is_not_double_recorded_when_resuming_twice(tmp_path: Path) -> None:
    sched = schedule_of(*[acm_call(i) for i in range(3)])
    ledger = Ledger(tmp_path / "ledger.jsonl")
    for _ in range(2):  # crash on acm0, resume, crash again on the redo of the same call
        with pytest.raises(KeyboardInterrupt):
            make_runner(tmp_path, sched, Fakes(acm_fn=interrupt_on(0)), ledger=ledger).run()
    result = make_runner(tmp_path, sched, Fakes(), ledger=ledger).run()
    assert result.status == "completed" and result.n_ok == 3
    records = prov(tmp_path)
    ids = [r.id for r in records if not isinstance(r, Relation)]
    assert len(ids) == len(set(ids)) and validate(records) == []
    assert ledger.outstanding() == []
    orphans = activities(records, KIND_ORPHAN)
    assert len(orphans) == len(reserves(ledger)) - len(attempts(records))


def test_crash_between_provenance_and_reconciliation_is_reconciled_without_duplicate_record(tmp_path: Path) -> None:
    sched = schedule_of(acm_call(0), acm_call(1))
    ledger = Ledger(tmp_path / "ledger.jsonl")
    make_runner(tmp_path, sched, Fakes(), ledger=ledger).run()
    # simulate the crash window: drop the last reconcile line so the attempt is recorded but unreconciled
    lines = (tmp_path / "ledger.jsonl").read_text().splitlines(keepends=True)
    assert json.loads(lines[-1])["type"] == "reconcile"
    dropped = json.loads(lines[-1])["attempt_id"]
    (tmp_path / "ledger.jsonl").write_text("".join(lines[:-1]))
    again = Fakes()
    result = make_runner(tmp_path, sched, again, ledger=ledger).run()
    assert again.n_calls == 0 and result.status == "completed"
    assert reconciles(ledger)[dropped]["basis"] == "worst_case_orphan"
    records = prov(tmp_path)
    assert len([a for a in activities(records) if a.id == dropped]) == 1
    assert validate(records) == []


def test_interrupt_in_a_translation_call_resumes_cleanly(tmp_path: Path) -> None:
    sched = schedule_of(tr_call(0), tr_call(1))

    def crash(n: int, p: Profile, prompt: str) -> TranslationOutcome:
        raise KeyboardInterrupt

    ledger = Ledger(tmp_path / "ledger.jsonl")
    ok_then_crash = Fakes(tr_fn=lambda n, p, prompt: tr_ok(p, prompt) if n == 0 else crash(n, p, prompt))
    with pytest.raises(KeyboardInterrupt):
        make_runner(tmp_path, sched, ok_then_crash, ledger=ledger).run()
    second = Fakes()
    result = make_runner(tmp_path, sched, second, ledger=ledger).run()
    assert result.n_ok == 2 and len(second.tr_calls) == 1
    assert validate(prov(tmp_path)) == []


def test_interrupted_final_retry_does_not_grant_extra_attempts(tmp_path: Path) -> None:
    """max_attempts=2: attempt 1 throttled, attempt 2 interrupted (counts). The resumed run must not exceed 2."""
    plan = make_plan(retry=dataclasses.replace(make_plan().retry, max_attempts=2))
    sched = schedule_of(acm_call(0))
    ledger = Ledger(tmp_path / "ledger.jsonl")

    def script(n: int, t: str) -> AcmOutcome:
        if n == 0:
            return acm_fail(t)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        make_runner(tmp_path, sched, Fakes(acm_fn=script), plan=plan, ledger=ledger).run()
    make_runner(tmp_path, sched, Fakes(acm_fn=lambda n, t: acm_fail(t)), plan=plan, ledger=ledger).run()
    assert len(reserves(ledger, "acm0")) <= plan.retry.max_attempts


# ================================================================== 7. temporal blocks

def test_block_starts_are_spaced_by_block_spacing(tmp_path: Path) -> None:
    plan = make_plan()
    spacing = plan.block_spacing_s
    clock = Clock()
    calls = [acm_call(i, block=i // 2) for i in range(6)]
    fakes = Fakes()

    def slow(n: int, text: str) -> AcmOutcome:
        clock.now += 7.0
        return acm_ok(text)

    fakes.acm_fn = slow
    result = make_runner(tmp_path, schedule_of(*calls), fakes, plan=plan, clock=clock).run()
    assert result.status == "completed"
    starts = sorted((a.attrs["block"], a.attrs["epoch"]) for a in activities(prov(tmp_path), KIND_BLOCK))
    assert [b for b, _ in starts] == [0, 1, 2]
    for (_, t0), (_, t1) in zip(starts, starts[1:]):
        assert t1 - t0 >= spacing - 1e-6
    assert len(clock.sleeps) == 2 and all(s <= spacing for s in clock.sleeps)


def test_no_wait_when_the_spacing_already_elapsed(tmp_path: Path) -> None:
    clock = Clock()

    def very_slow(n: int, text: str) -> AcmOutcome:
        clock.now += make_plan().block_spacing_s + 5
        return acm_ok(text)

    fakes = Fakes(acm_fn=very_slow)
    make_runner(tmp_path, schedule_of(acm_call(0, block=0), acm_call(1, block=1)), fakes, clock=clock).run()
    assert clock.sleeps == []


def test_resumed_run_does_not_wait_again_for_a_started_block(tmp_path: Path) -> None:
    plan = make_plan()
    clock = Clock()
    calls = [acm_call(0, block=0), acm_call(1, block=1), acm_call(2, block=1), acm_call(3, block=2)]
    ledger = Ledger(tmp_path / "ledger.jsonl")
    with pytest.raises(KeyboardInterrupt):
        make_runner(tmp_path, schedule_of(*calls), Fakes(acm_fn=interrupt_on(1)), plan=plan, clock=clock,
                    ledger=ledger).run()
    (block1,) = [a for a in activities(prov(tmp_path), KIND_BLOCK) if a.attrs["block"] == 1]
    sleeps_before = list(clock.sleeps)
    assert len(sleeps_before) == 1  # waited once, for block 1
    clock.now += 60  # restart shortly after the crash: block 1 is still inside its spacing window
    result = make_runner(tmp_path, schedule_of(*calls), Fakes(), plan=plan, clock=clock, ledger=ledger).run()
    assert result.status == "completed"
    assert len(clock.sleeps) == 2  # only the wait for block 2, none again for block 1
    blocks = activities(prov(tmp_path), KIND_BLOCK)
    assert Counter(a.attrs["block"] for a in blocks) == {0: 1, 1: 1, 2: 1}
    epoch2 = next(a.attrs["epoch"] for a in blocks if a.attrs["block"] == 2)
    assert epoch2 - block1.attrs["epoch"] >= plan.block_spacing_s - 1e-6


def test_completed_block_zero_is_not_restarted_on_resume(tmp_path: Path) -> None:
    calls = [acm_call(0, block=0), acm_call(1, block=0)]
    ledger = Ledger(tmp_path / "ledger.jsonl")
    with pytest.raises(KeyboardInterrupt):
        make_runner(tmp_path, schedule_of(*calls), Fakes(acm_fn=interrupt_on(1)), ledger=ledger).run()
    clock = Clock()
    make_runner(tmp_path, schedule_of(*calls), Fakes(), clock=clock, ledger=ledger).run()
    assert len(activities(prov(tmp_path), KIND_BLOCK)) == 1 and clock.sleeps == []


# ================================================================== 8. raw storage

def test_raw_body_is_stored_byte_for_byte(tmp_path: Path) -> None:
    raw = b'{"Entities":[{"Text":"caf\xc3\xa9"}],\r\n"x":\t1}\n\x00\xff'
    fakes = Fakes(acm_fn=lambda n, t: acm_ok(t, raw=raw))
    make_runner(tmp_path, schedule_of(acm_call(0)), fakes).run()
    records = prov(tmp_path)
    (act,) = attempts(records)
    path = tmp_path / "run" / "raw" / f"{fname(act.id)}.body"
    assert path.read_bytes() == raw
    out = next(r for r in records if isinstance(r, Entity) and r.kind == "acm_response")
    assert out.attrs["body_file"] == f"raw/{fname(act.id)}.body" and "body_refused" not in out.attrs
    import hashlib
    assert out.sha256 == hashlib.sha256(raw).hexdigest()


def test_translation_raw_body_and_output_text_are_stored(tmp_path: Path) -> None:
    raw = '{"output":{"message":"olá"}}'.encode()
    fakes = Fakes(tr_fn=lambda n, p, prompt: tr_ok(p, prompt, raw=raw, output="Héllo wörld"))
    make_runner(tmp_path, schedule_of(tr_call(0)), fakes).run()
    (act,) = attempts(prov(tmp_path))
    run = tmp_path / "run"
    assert (run / "raw" / f"{fname(act.id)}.body").read_bytes() == raw
    assert (run / "outputs" / f"{fname(act.id)}.txt").read_bytes() == "Héllo wörld".encode()


def aws_key() -> str:
    return "AKIA" + "Q" * 16


def test_raw_body_with_an_aws_key_is_refused_and_never_written(tmp_path: Path) -> None:
    key = aws_key()
    raw = json.dumps({"Entities": [], "note": f"leaked {key} here"}).encode()
    fakes = Fakes(acm_fn=lambda n, t: acm_ok(t, raw=raw, response={"Entities": []}))
    ledger = Ledger(tmp_path / "ledger.jsonl")
    result = make_runner(tmp_path, schedule_of(acm_call(0)), fakes, ledger=ledger).run()
    assert result.n_ok == 1
    records = prov(tmp_path)
    out = next(r for r in records if isinstance(r, Entity) and r.kind == "acm_response")
    assert "body_refused" in out.attrs and "body_file" not in out.attrs
    assert key not in out.attrs["body_refused"]
    for path, data in all_run_bytes(tmp_path):
        assert key.encode() not in data, path


def test_aws_key_inside_the_parsed_response_does_not_abort_the_run_or_reach_disk(tmp_path: Path) -> None:
    key = aws_key()
    response = {"Entities": [], "echo": key}
    raw = json.dumps(response).encode()
    fakes = Fakes(acm_fn=lambda n, t: acm_ok(t, raw=raw, response=response))
    ledger = Ledger(tmp_path / "ledger.jsonl")
    result = make_runner(tmp_path, schedule_of(acm_call(0), acm_call(1)), fakes, ledger=ledger).run()
    assert result.n_ok == 2 and ledger.outstanding() == []
    for path, data in all_run_bytes(tmp_path):
        assert key.encode() not in data, path


def test_aws_key_in_translation_output_text_never_reaches_disk(tmp_path: Path) -> None:
    key = aws_key()
    fakes = Fakes(tr_fn=lambda n, p, prompt: tr_ok(p, prompt, output=f"secret {key}", raw=f"x {key}".encode(),
                                                   response={"output": "clean"}))
    ledger = Ledger(tmp_path / "ledger.jsonl")
    tr = tr_call(0)
    result = make_runner(tmp_path, schedule_of(tr, pipe_call(1, tr)), fakes, ledger=ledger).run()
    # the leak must not break the run; the child is not executed on an input that could not be stored
    assert result.n_ok == 1 and result.n_not_executed == 1 and result.status == "completed"
    for path, data in all_run_bytes(tmp_path):
        assert key.encode() not in data, path


def test_aws_key_in_an_error_message_never_reaches_disk(tmp_path: Path) -> None:
    key = aws_key()
    fakes = Fakes(acm_fn=lambda n, t: acm_fail(t, "ValidationException", message=f"bad credentials {key}"))
    make_runner(tmp_path, schedule_of(acm_call(0)), fakes).run()
    for path, data in all_run_bytes(tmp_path):
        assert key.encode() not in data, path


# ================================================================== 9. locking and manifest

def test_second_runner_on_a_locked_run_dir_raises_run_error(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    fakes = Fakes()
    with open(run_dir / ".lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(RunError):
            make_runner(tmp_path, schedule_of(acm_call(0)), fakes).run()
    assert fakes.n_calls == 0
    assert reserves(Ledger(tmp_path / "ledger.jsonl")) == []
    # the lock is free again: the run now works
    assert make_runner(tmp_path, schedule_of(acm_call(0)), fakes).run().n_ok == 1


def test_lock_is_released_after_an_interrupted_run(tmp_path: Path) -> None:
    sched = schedule_of(acm_call(0), acm_call(1))
    with pytest.raises(KeyboardInterrupt):
        make_runner(tmp_path, sched, Fakes(acm_fn=interrupt_on(0))).run()
    assert make_runner(tmp_path, sched, Fakes()).run().status == "completed"


def test_manifest_from_another_schedule_is_refused(tmp_path: Path) -> None:
    make_runner(tmp_path, schedule_of(acm_call(0), acm_call(1)), Fakes()).run()
    other = Fakes()
    with pytest.raises(RunError):
        make_runner(tmp_path, schedule_of(acm_call(0), acm_call(2)), other).run()
    assert other.n_calls == 0


def test_manifest_from_another_run_id_is_refused(tmp_path: Path) -> None:
    sched = schedule_of(acm_call(0))
    make_runner(tmp_path, sched, Fakes()).run()
    other = Fakes()
    with pytest.raises(RunError):
        make_runner(tmp_path, sched, other, run_id="run2").run()
    assert other.n_calls == 0


def test_run_manifest_records_hashes_and_agent(tmp_path: Path) -> None:
    sched = schedule_of(acm_call(0))
    make_runner(tmp_path, sched, Fakes()).run()
    m = json.loads((tmp_path / "run" / "run.json").read_text())
    assert m["run_id"] == "run1" and m["plan_sha256"] == "p" * 64 and m["region"] == "us-east-2"
    assert m["agent_id"] in {r.id for r in prov(tmp_path) if not isinstance(r, Relation)}


# ================================================================== 10. imports

def test_runner_import_does_not_load_boto() -> None:
    code = ("import sys, habench.campaign.runner\n"
            "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('boto3', 'botocore'))\n"
            "assert not bad, bad\n")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert proc.returncode == 0, proc.stderr
