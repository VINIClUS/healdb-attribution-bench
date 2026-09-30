import copy
import multiprocessing
from pathlib import Path

import pytest
import yaml

from habench.campaign.money import (
    CapExceeded,
    Ledger,
    PaidAuthorization,
    PaidCallRefused,
    authorize_paid,
)
from habench.campaign.plan import plan_from_dict

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "repro" / "campaign_plan.template.yaml"


def _plan(priced: bool = True):
    d = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    d = copy.deepcopy(d)
    if priced:
        d["profiles"] = [
            {"name": "commercial", "model_id": "m-com", "temperature": None},
            {"name": "commercial_t0", "model_id": "m-com", "temperature": 0.0},
            {"name": "open_weights", "model_id": "m-open", "temperature": None},
        ]
        d["token_prices"] = {"m-com": {"input_usd_per_mtok": 1.0, "output_usd_per_mtok": 2.0},
                             "m-open": {"input_usd_per_mtok": 0.5, "output_usd_per_mtok": 0.5}}
    return plan_from_dict(d)


GOOD_ENV = {"HAB_PAID_CALLS": "1"}


def test_authorize_requires_every_condition():
    plan = _plan()
    models = {"m-com", "m-open"}
    auth = authorize_paid(paid_flag=True, budget_usd=5.0, plan=plan, model_ids=models, env=GOOD_ENV)
    assert auth.budget_usd == 5.0 and auth.cap_usd == 30.0
    bad = [
        dict(paid_flag=True, budget_usd=5.0, env={}),
        dict(paid_flag=True, budget_usd=5.0, env={"HAB_PAID_CALLS": "true"}),
        dict(paid_flag=False, budget_usd=5.0, env=GOOD_ENV),
        dict(paid_flag=True, budget_usd=None, env=GOOD_ENV),
        dict(paid_flag=True, budget_usd=0.0, env=GOOD_ENV),
    ]
    for kw in bad:
        with pytest.raises(PaidCallRefused):
            authorize_paid(plan=plan, model_ids=models, **kw)
    with pytest.raises(PaidCallRefused, match="no price"):
        authorize_paid(paid_flag=True, budget_usd=5.0, plan=plan, model_ids={"m-com", "m-unknown"}, env=GOOD_ENV)


def test_placeholder_models_never_authorized():
    plan = _plan(priced=False)
    with pytest.raises(PaidCallRefused, match="MODEL_ID"):
        authorize_paid(paid_flag=True, budget_usd=5.0, plan=plan,
                       model_ids={p.model_id for p in plan.profiles}, env=GOOD_ENV)


def test_default_env_is_process_env_and_tests_never_have_the_flag():
    with pytest.raises(PaidCallRefused, match="HAB_PAID_CALLS"):
        authorize_paid(paid_flag=True, budget_usd=5.0, plan=_plan(), model_ids={"m-com"})


def test_authorization_cannot_be_forged():
    with pytest.raises(PaidCallRefused):
        PaidAuthorization(budget_usd=1.0, cap_usd=1.0, model_ids=frozenset(), token=object())


def test_reserve_reconcile_and_caps(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    led.reserve(attempt_id="a1", run_id="r1", usd=10.0, cap_usd=30.0, run_budget_usd=20.0)
    assert led.totals().spent_usd == 10.0 and led.totals().outstanding_usd == 10.0
    led.reconcile(attempt_id="a1", usd=4.0, basis="measured")
    assert led.totals().spent_usd == 4.0 and led.totals().outstanding_usd == 0.0
    with pytest.raises(CapExceeded, match="run budget"):
        led.reserve(attempt_id="a2", run_id="r1", usd=16.1, cap_usd=30.0, run_budget_usd=20.0)
    led.reserve(attempt_id="a2", run_id="r1", usd=16.0, cap_usd=30.0, run_budget_usd=20.0)  # exactly at budget
    # cumulative cap across runs: 20 spent, a new run with a big budget still stops at 30
    with pytest.raises(CapExceeded, match="cap"):
        led.reserve(attempt_id="b1", run_id="r2", usd=10.5, cap_usd=30.0, run_budget_usd=100.0)
    before = led.entries()
    with pytest.raises(CapExceeded):
        led.reserve(attempt_id="b2", run_id="r2", usd=11.0, cap_usd=30.0, run_budget_usd=100.0)
    assert led.entries() == before  # a refused reservation writes nothing


def test_outstanding_reservations_count_and_orphans(tmp_path):
    path = tmp_path / "ledger.jsonl"
    led = Ledger(path)
    led.reserve(attempt_id="a1", run_id="r1", usd=1.0, cap_usd=30.0, run_budget_usd=5.0)
    # a new process (resume) sees the unreconciled reservation as spent
    again = Ledger(path)
    assert again.totals().spent_usd == 1.0
    assert [e["attempt_id"] for e in again.outstanding("r1")] == ["a1"]
    assert again.reconcile_orphans("r1") == 1
    assert again.totals().spent_usd == 1.0 and again.outstanding("r1") == []
    with pytest.raises(ValueError, match="already reconciled"):
        again.reconcile(attempt_id="a1", usd=0.0, basis="measured")
    with pytest.raises(ValueError, match="never reserved"):
        again.reconcile(attempt_id="zz", usd=0.0, basis="measured")
    with pytest.raises(ValueError, match="already reserved"):
        again.reserve(attempt_id="a1", run_id="r1", usd=0.1, cap_usd=30.0, run_budget_usd=5.0)


def test_reconcile_above_reservation_is_flagged_not_hidden(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    led.reserve(attempt_id="a", run_id="r", usd=0.1, cap_usd=30.0, run_budget_usd=5.0)
    led.reconcile(attempt_id="a", usd=0.2, basis="measured")
    assert led.entries()[-1]["exceeded_reservation"] is True
    assert led.totals().spent_usd == pytest.approx(0.2)


def test_dry_copy_never_writes(tmp_path):
    path = tmp_path / "l.jsonl"
    led = Ledger(path)
    led.reserve(attempt_id="a", run_id="r", usd=2.0, cap_usd=30.0, run_budget_usd=5.0)
    raw = path.read_bytes()
    dry = led.dry_copy()
    dry.reserve(attempt_id="d", run_id="dry", usd=3.0, cap_usd=30.0, run_budget_usd=5.0)
    assert dry.totals().spent_usd == 5.0
    assert path.read_bytes() == raw


def _reserve_many(path: str, prefix: str, n: int) -> None:
    led = Ledger(Path(path))
    for i in range(n):
        try:
            led.reserve(attempt_id=f"{prefix}{i}", run_id=prefix, usd=1.0, cap_usd=15.0, run_budget_usd=100.0)
        except CapExceeded:
            pass


def test_concurrent_reservations_respect_the_cap(tmp_path):
    path = tmp_path / "l.jsonl"
    ctx = multiprocessing.get_context("fork")
    procs = [ctx.Process(target=_reserve_many, args=(str(path), p, 10)) for p in ("x", "y", "z")]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    t = Ledger(path).totals()
    assert t.spent_usd == 15.0 and t.n_attempts == 15
