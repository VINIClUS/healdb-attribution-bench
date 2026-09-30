import dataclasses
from collections import Counter
from pathlib import Path

import pytest
import yaml

from habench.campaign.calls import Condition, Role, Schedule, Service, sha256_text
from habench.campaign.plan import Plan, plan_from_dict
from habench.campaign.schedule import (ManifestRow, ScheduleError, _allocate, check_schedule, open_groups,
                                       plan_pilot, plan_smoke, read_manifest, select_groups)
from habench.campaign.texts import DictTextSource
from habench.types import SealedError

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "data" / "campaign" / "split_manifest.csv"


def make_plan(**over: int) -> Plan:
    d = yaml.safe_load((ROOT / "repro" / "campaign_plan.template.yaml").read_text(encoding="utf-8"))
    plan = plan_from_dict(d)
    return dataclasses.replace(plan, **over) if over else plan


def synthetic() -> tuple[list[ManifestRow], DictTextSource]:
    """80 open groups (strata a/b/c = 40/25/15), 10 test, 5 reserve; two open medications ineligible."""
    rows: list[ManifestRow] = []
    sub: dict[int, str | None] = {}
    pt: dict[int, str | None] = {}
    med = 1000

    def add(n: int, partition: str, stratum: str) -> None:
        nonlocal med
        for _ in range(n):
            meds = tuple(range(med, med + 1 + med % 3))
            med += 5
            rows.append(ManifestRow(f"g{len(rows):04d}", partition, meds, len(meds), stratum, 0.5))
            for m in meds:
                sub[m] = f"submitted text {m} \n"
                pt[m] = f"indicação em português {m}  "

    add(20, "dev", "a"); add(20, "cal", "a"); add(15, "dev", "b"); add(10, "cal", "b")
    add(8, "dev", "c"); add(7, "cal", "c"); add(10, "test", "a"); add(5, "reserve", "b")
    sub[rows[0].medications[0]] = None
    pt[rows[1].medications[0]] = "short"
    return rows, DictTextSource(sub, pt)


class GuardedSource(DictTextSource):
    """Fails if a text is requested for a medication outside dev/cal groups."""

    def __init__(self, base: DictTextSource, forbidden: set[int]) -> None:
        super().__init__(base._submitted, base._pt)
        self.forbidden = forbidden

    def submitted_text(self, med: int) -> str | None:
        assert med not in self.forbidden, "text requested for a sealed/non-open medication"
        return super().submitted_text(med)

    def pt_indication(self, med: int) -> str | None:
        assert med not in self.forbidden, "text requested for a sealed/non-open medication"
        return super().pt_indication(med)


def meds_outside(rows: list[ManifestRow], open_parts: set[str]) -> set[int]:
    return {m for r in rows if r.partition not in open_parts for m in r.medications}


def test_read_manifest_fixture() -> None:
    rows, sha = read_manifest(FIXTURE)
    assert [r.partition for r in rows] == ["dev", "cal", "test", "reserve"]
    assert rows[0].medications == (101, 102) and rows[0].inclusion_prob == 0.5
    assert len(sha) == 64


def test_sealing() -> None:
    rows, _ = read_manifest(FIXTURE)
    assert [r.partition for r in open_groups(rows, ["dev", "cal"])] == ["dev", "cal"]
    with pytest.raises(SealedError):
        open_groups(rows, ["dev", "test"])
    with pytest.raises(SealedError):
        select_groups(rows, ["gaaaaaaaaaaa1", "gaaaaaaaaaaa3"])
    assert select_groups(rows, ["gaaaaaaaaaaa1"])[0].group_id == "gaaaaaaaaaaa1"


def test_smoke_counts_dev_only_and_no_other_texts() -> None:
    rows, src = synthetic()
    plan = make_plan()
    s = plan_smoke(rows, "m", plan, "p", GuardedSource(src, meds_outside(rows, {"dev"})))
    dev_groups = {r.group_id for r in rows if r.partition == "dev"}
    assert len(s.calls) == 100
    assert {c.group_id for c in s.calls} <= dev_groups
    assert len({c.group_id for c in s.calls}) == 20
    assert all(c.condition is Condition.SMOKE and c.role is Role.SMOKE and c.block == 0 for c in s.calls)
    assert all(c.service is Service.ACM and c.input_sha256 == sha256_text(c.input_text or "") for c in s.calls)
    assert set(Counter(c.medication for c in s.calls).values()) == {5}
    assert [c.order for c in s.calls] == list(range(100))
    assert s.to_json() == plan_smoke(rows, "m", plan, "p", src).to_json()
    assert Schedule.from_json(s.to_json()) == s


def test_smoke_representative_and_log() -> None:
    row = ManifestRow("g", "dev", (1, 2, 3, 4, 5), 5, "s", 1.0)
    sub = {1: None, 2: "", 3: "x" * 10_001, 4: "x" * 10_000, 5: "y"}
    s = plan_smoke([row], "m", make_plan(smoke_texts=1, smoke_repetitions=1), "p", DictTextSource(sub, {}))
    assert s.calls[0].medication == 4
    assert [m for m, _ in s.excluded] == [1, 2, 3]
    assert s.excluded[0][1] == "acm: no submitted text"
    assert "empty" in s.excluded[1][1] and "longer" in s.excluded[2][1]


def test_smoke_not_enough_groups() -> None:
    rows, src = synthetic()
    with pytest.raises(ValueError):
        plan_smoke(rows, "m", make_plan(smoke_texts=1000), "p", src)


def test_pilot_counts_roles_and_blocks() -> None:
    rows, src = synthetic()
    plan = make_plan()
    forbidden = meds_outside(rows, {"dev", "cal"})
    s = plan_pilot(rows, "m", plan, "p", GuardedSource(src, forbidden))
    cnt = Counter(c.condition for c in s.calls)
    assert cnt == {Condition.ACM_ISOLATED: 600, Condition.TRANSLATION_ISOLATED: 1800,
                   Condition.FULL_PIPELINE: 1800}
    assert len({c.group_id for c in s.calls}) == 60
    assert not {c.medication for c in s.calls} & forbidden
    refs: Counter = Counter()
    for c in s.calls:
        if c.condition is not Condition.FULL_PIPELINE and c.role is Role.REFERENCE:
            refs[(c.medication, c.condition, c.profile)] += 1
    assert len(refs) == 60 * 4 and set(refs.values()) == {6}
    assert {c.block for c in s.calls} == set(range(10))
    assert [c.block for c in s.calls] == sorted(c.block for c in s.calls)
    assert [c.order for c in s.calls] == list(range(len(s.calls)))
    by_id = {c.call_id: c for c in s.calls}
    full = [c for c in s.calls if c.condition is Condition.FULL_PIPELINE]
    assert all(c.parent in by_id and by_id[c.parent].order < c.order and c.input_text is None for c in full)
    assert all(c.call_id != c.parent for c in full)
    acm = next(c for c in s.calls if c.condition is Condition.ACM_ISOLATED)
    assert acm.input_text == src.submitted_text(acm.medication) and acm.profile is None
    tr = next(c for c in s.calls if c.condition is Condition.TRANSLATION_ISOLATED)
    assert tr.input_text == src.pt_indication(tr.medication) and tr.profile is not None
    check_schedule(s, plan)


def test_pilot_eligibility_log() -> None:
    rows, src = synthetic()
    s = plan_pilot(rows, "m", make_plan(), "p", src)
    log = dict(s.excluded)
    open_meds = {m for r in rows if r.partition in ("dev", "cal") for m in r.medications}
    assert set(log) <= open_meds
    assert all(reason.startswith(("acm:", "translate:")) for reason in log.values())
    selected = {c.group_id for c in s.calls}
    for g, expect in ((rows[0], "acm: no submitted text"), (rows[1], "translate: indication length <= 10")):
        if g.group_id in selected:
            assert log[g.medications[0]] == expect
            assert g.medications[0] not in {c.medication for c in s.calls}


def test_pilot_reproducible_and_seed_sensitive() -> None:
    rows, src = synthetic()
    a = plan_pilot(rows, "m", make_plan(), "p", src).to_json()
    assert a == plan_pilot(rows, "m", make_plan(), "p", src).to_json()
    a_s = Schedule.from_json(a)
    b = plan_pilot(rows, "m", make_plan(seed=7), "p", src)
    assert [c.call_id for c in a_s.calls] != [c.call_id for c in b.calls]
    assert [c.role for c in a_s.calls] != [c.role for c in b.calls]


def test_stratification_proportions() -> None:
    assert _allocate({"a": 40, "b": 25, "c": 15}, 60) == {"a": 30, "b": 19, "c": 11}
    assert _allocate({"a": 10, "b": 1, "c": 1}, 6) == {"a": 5, "b": 1, "c": 0}  # remainder tie by name
    assert _allocate({"a": 3, "b": 1}, 4) == {"a": 3, "b": 1}  # everything taken: capped at size
    assert _allocate({"a": 1, "b": 1}, 1) == {"a": 1, "b": 0}  # tie by name
    rows, src = synthetic()
    s = plan_pilot(rows, "m", make_plan(), "p", src)
    stratum = {r.group_id: r.stratum for r in rows}
    assert Counter(stratum[g] for g in {c.group_id for c in s.calls}) == {"a": 30, "b": 19, "c": 11}


def test_pilot_not_enough_eligible() -> None:
    rows, src = synthetic()
    with pytest.raises(ValueError):
        plan_pilot(rows, "m", make_plan(pilot_texts=81), "p", src)
    with pytest.raises(ValueError):
        plan_pilot(rows, "m", make_plan(), "p", DictTextSource(src._submitted, {}))


def test_pilot_never_selects_test_groups() -> None:
    rows, src = synthetic()
    s = plan_pilot(rows, "m", make_plan(), "p", src)
    closed = {r.group_id for r in rows if r.partition not in ("dev", "cal")}
    assert not {c.group_id for c in s.calls} & closed


def test_check_schedule_catches_breakage() -> None:
    rows, src = synthetic()
    plan = make_plan(pilot_texts=6)
    s = plan_pilot(rows, "m", plan, "p", src)
    calls = list(s.calls)

    def fails(new: list) -> None:  # type: ignore[type-arg]
        with pytest.raises(ScheduleError):
            check_schedule(dataclasses.replace(s, calls=tuple(new)), plan)

    fails(calls + [calls[0]])  # duplicate id and order
    i = next(k for k, c in enumerate(calls)
             if c.condition is Condition.ACM_ISOLATED and c.role is Role.EVALUATION)
    fails(calls[:i] + [dataclasses.replace(calls[i], role=Role.REFERENCE)] + calls[i + 1:])  # 7 references
    j = next(k for k, c in enumerate(calls) if c.condition is Condition.FULL_PIPELINE)
    other = Role.EVALUATION if calls[j].role is Role.REFERENCE else Role.REFERENCE
    fails(calls[:j] + [dataclasses.replace(calls[j], role=other)] + calls[j + 1:])  # role not inherited
    parent = next(k for k, c in enumerate(calls) if c.call_id == calls[j].parent)
    swapped = list(calls)
    swapped[parent] = dataclasses.replace(calls[parent], order=calls[j].order)
    swapped[j] = dataclasses.replace(calls[j], order=calls[parent].order)
    fails(swapped)  # child before parent
    fails([c for c in calls if c.block != 3])  # block 3 lacks every condition
