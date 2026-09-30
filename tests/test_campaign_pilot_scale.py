"""Pilot-scale estimate and dry run (60 texts × 3 profiles × 10) on synthetic 400-character texts."""

from pathlib import Path

import pytest
import yaml

from habench.campaign.estimator import estimate, format_estimate
from habench.campaign.money import Ledger
from habench.campaign.plan import plan_from_dict
from habench.campaign.runner import Runner
from habench.campaign.schedule import ManifestRow, plan_pilot
from habench.campaign.texts import DictTextSource

ROOT = Path(__file__).resolve().parents[1]


def _plan():
    d = yaml.safe_load((ROOT / "repro" / "campaign_plan.template.yaml").read_text(encoding="utf-8"))
    d["profiles"] = [{"name": "commercial", "model_id": "m-com", "temperature": None},
                     {"name": "commercial_t0", "model_id": "m-com", "temperature": 0.0},
                     {"name": "open_weights", "model_id": "m-open", "temperature": None}]
    d["token_prices"] = {"m-com": {"input_usd_per_mtok": 0.15, "output_usd_per_mtok": 0.60},
                         "m-open": {"input_usd_per_mtok": 0.20, "output_usd_per_mtok": 0.20}}
    return plan_from_dict(d)


def _pilot():
    plan = _plan()
    rows = [ManifestRow(f"g{i:012d}", "dev" if i % 2 else "cal", (1000 + i,), 1, f"s{i % 3}", 0.5)
            for i in range(80)]
    acm_text = "What this medication is indicated for:\n" + "x" * 359 + "\n\n"  # 400 characters
    texts = DictTextSource({1000 + i: acm_text for i in range(80)}, {1000 + i: " " + "p" * 399 for i in range(80)})
    return plan, plan_pilot(rows, "m", plan, "p", texts)


def test_pilot_hard_bound_exceeds_cap_but_expected_proxy_is_reported():
    plan, schedule = _pilot()
    e = estimate(schedule, plan)
    print(format_estimate(e))
    assert e.counts[("acm", "full_pipeline")] == 1800
    # hard bound: 1,800 pipeline calls at the 10,000-character limit = US$ 90 > cap
    assert e.max_call_usd[("acm", "full_pipeline")] == pytest.approx(0.05)
    assert e.within_cap is False
    # proxy: 400 characters = 4 units = US$ 0.002 per call
    assert e.expected_full_pipeline_usd == pytest.approx(1800 * 0.002)


def test_pilot_dry_run_is_conservative_and_stops_at_the_cap(tmp_path):
    plan, schedule = _pilot()
    result = Runner(schedule, plan, run_dir=tmp_path / "run", run_id="dry", ledger=Ledger(None),
                    backends=None, budget_usd=plan.cap_usd).run()
    assert result.status == "dry_run" and result.stop_reason is not None
    assert 0 < result.n_planned < len(schedule.calls)
    assert not (tmp_path / "run").exists()
