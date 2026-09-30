"""End-to-end smoke on 5 dev groups (T21): real scenarios → truth → views → isolated runs, then M against the oracle
under L2-M × R-A at b = 64 (enough for |D| ≤ 6). Heavy: `uv run pytest -m dumps tests/test_runner_smoke.py`.
The recorded smoke run uses the CLI instead, writing to HAB_DATA_DIR (see docs/status/lead-gamma.md)."""

from __future__ import annotations

import pytest

from habench.runner.batch import Batch, load_inputs
from habench.runner.check import check_m
from habench.scenarios.generate import generate_with_report

SEED = 20260930


@pytest.mark.dumps
def test_smoke_five_dev_groups(tmp_path):
    evidence, hier, texts = load_inputs("dev")
    scenarios, report = generate_with_report("dev", seed=SEED, evidence=evidence, hier=hier, max_groups=5)
    assert scenarios and not report.errors
    batch = Batch("dev", "smoke", evidence, hier, texts, data_dir=tmp_path, methods=("m", "b3"), info_fraction=0.0)
    counts = batch.run(scenarios)
    assert counts["contrasts"] == len(scenarios) and counts["errors"] == 0
    res = check_m(tmp_path, "dev", "smoke")
    assert res.contrasts == len(scenarios) and res.queries > 0
    assert not res.mismatches, res.mismatches[:10]
