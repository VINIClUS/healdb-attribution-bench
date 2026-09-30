"""Smoke test of scenario generation on real v1 evidence (dev groups only). Run once: -m dumps."""

import time

import pytest

from habench.data import splits
from habench.scenarios.generate import generate_with_report, manifest_groups, scenarios_canonical

pytestmark = pytest.mark.dumps


def test_generate_on_three_real_dev_groups():
    from habench.pipeline.evidence import load_evidence
    from habench.pipeline.mapping import load_hierarchy

    groups = [g for g in manifest_groups("dev") if 2 <= len(g[1]) <= 4][:3]  # deterministic, small
    assert len(groups) == 3
    meds = sorted(m for _, ms in groups for m in ms)
    assert all(splits.partition_of_med(m) == "dev" for m in meds)
    t0 = time.perf_counter()
    ev = load_evidence("v1", meds)
    hier = load_hierarchy("v1")
    t1 = time.perf_counter()
    scs, rep = generate_with_report("dev", seed=20260930, groups=groups, evidence=ev, hier=hier)
    t2 = time.perf_counter()
    print(f"\nload {t1 - t0:.1f}s, generate {t2 - t1:.1f}s, {len(scs)} scenarios")
    print("produced:", dict(sorted(rep.produced.items())))
    print("dropped:", dict(sorted(rep.dropped.items())))
    print("ineligible:", dict(rep.ineligible), "errors:", rep.errors)
    for fam in ("N", "F", "M", "O", "X", "I"):
        made = sum(n for k, n in rep.produced.items() if k.startswith(fam + "/"))
        reasons = {k: n for k, n in rep.dropped.items() if k.startswith(fam + ":")}
        print(fam, made, reasons)
        assert made or reasons, f"family {fam}: neither scenarios nor a recorded reason"
    assert not rep.errors  # no N contrast with a changed query, no endpoint mismatch
    for s in scs:
        s.contrast.validate()  # sealed check on
        assert all(0 < p <= 1 for p in s.inclusion.values())
    again, _ = generate_with_report("dev", seed=20260930, groups=groups, evidence=ev, hier=hier)
    assert scenarios_canonical(again) == scenarios_canonical(scs)
