"""Seeded, reproducible campaign schedules: smoke test and pilot (protocol §§9.2-9.3).

Only dev/cal groups are ever open: the sealed test partition raises SealedError and its texts are never requested.
"""

import csv
import hashlib
import math
import random
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from habench.campaign.calls import (ACM_TEXT_LIMIT, Condition, Role, Schedule, ScheduledCall, Service,
                                    sha256_text)
from habench.campaign.plan import Plan
from habench.campaign.texts import TextSource
from habench.types import SealedError

PARTITIONS = ("dev", "cal", "test", "reserve")
TRANSLATION_MIN_LENGTH = 10  # HealDB blanks translations of indications with length <= 10


class ScheduleError(ValueError):
    """A schedule violates the §9.2-9.3 design constraints."""


@dataclass(frozen=True, slots=True)
class ManifestRow:
    group_id: str
    partition: str
    medications: tuple[int, ...]
    n_medications: int
    stratum: str
    inclusion_prob: float


def read_manifest(path: Path) -> tuple[list[ManifestRow], str]:
    """Rows of repro/split_manifest.csv and the sha256 of the file bytes."""
    raw = path.read_bytes()
    rows: list[ManifestRow] = []
    with open(path, newline="", encoding="utf-8") as f:
        for rec in csv.DictReader(f):
            meds = tuple(int(m) for m in rec["medications"].split(";"))
            row = ManifestRow(group_id=rec["group_id"], partition=rec["partition"], medications=meds,
                              n_medications=int(rec["n_medications"]), stratum=rec["stratum"],
                              inclusion_prob=float(rec["inclusion_prob"]))
            if row.partition not in PARTITIONS:
                raise ValueError(f"{row.group_id}: unknown partition {row.partition!r}")
            if row.n_medications != len(meds):
                raise ValueError(f"{row.group_id}: n_medications does not match medications")
            rows.append(row)
    return rows, hashlib.sha256(raw).hexdigest()


def open_groups(rows: Iterable[ManifestRow], partitions: Iterable[str]) -> list[ManifestRow]:
    """Rows of the requested partitions; asking for the sealed test partition raises SealedError."""
    wanted = set(partitions)
    if "test" in wanted:
        raise SealedError("the test partition is sealed")
    unknown = wanted - set(PARTITIONS)
    if unknown:
        raise ValueError(f"unknown partitions {sorted(unknown)}")
    return [r for r in rows if r.partition in wanted]


def select_groups(rows: Iterable[ManifestRow], group_ids: Iterable[str]) -> list[ManifestRow]:
    """Rows for explicit group ids; a test group raises SealedError."""
    by_id = {r.group_id: r for r in rows}
    out = []
    for gid in group_ids:
        if gid not in by_id:
            raise ValueError(f"unknown group id {gid!r}")
        if by_id[gid].partition == "test":
            raise SealedError(f"group {gid} belongs to the sealed test partition")
        out.append(by_id[gid])
    return out


def _acm_reasons(text: str | None) -> list[str]:
    if text is None:
        return ["acm: no submitted text"]
    if text == "":
        return ["acm: empty submitted text"]
    if len(text) > ACM_TEXT_LIMIT:
        return [f"acm: text longer than {ACM_TEXT_LIMIT} characters"]
    return []


def _translation_reasons(pt: str | None) -> list[str]:
    if pt is None:
        return ["translate: no Portuguese indication"]
    if pt.strip() == "":
        return ["translate: blank Portuguese indication"]
    if len(pt) <= TRANSLATION_MIN_LENGTH:
        return [f"translate: indication length <= {TRANSLATION_MIN_LENGTH}"]
    return []


def _representative(row: ManifestRow, texts: TextSource, need_translation: bool,
                    excluded: list[tuple[int, str]]) -> int | None:
    """Smallest eligible medication of the group; every skipped medication is logged with its reasons."""
    for med in sorted(row.medications):
        reasons = _acm_reasons(texts.submitted_text(med))
        if need_translation:
            reasons += _translation_reasons(texts.pt_indication(med))
        if not reasons:
            return med
        excluded.append((med, "; ".join(reasons)))
    return None


def _rng(seed: int, *tag: object) -> random.Random:
    digest = hashlib.sha256("|".join([str(seed), *map(str, tag)]).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _call_id(kind: str, seed: int, condition: Condition, med: int, profile: str | None, r: int) -> str:
    key = "|".join([kind, str(seed), condition.value, str(med), profile or "", str(r)])
    return "c" + hashlib.sha256(key.encode()).hexdigest()[:16]


def plan_smoke(rows: Sequence[ManifestRow], manifest_sha256: str, plan: Plan, plan_sha256: str,
               texts: TextSource) -> Schedule:
    dev = sorted(open_groups(rows, ["dev"]), key=lambda r: r.group_id)
    rng = random.Random(plan.seed)
    drawn = rng.sample(dev, len(dev))
    excluded: list[tuple[int, str]] = []
    chosen: list[tuple[ManifestRow, int]] = []
    for row in drawn:
        if len(chosen) == plan.smoke_texts:
            break
        med = _representative(row, texts, False, excluded)
        if med is not None:
            chosen.append((row, med))
    if len(chosen) < plan.smoke_texts:
        raise ValueError(f"only {len(chosen)} eligible dev groups for {plan.smoke_texts} smoke texts")
    calls = []
    for row, med in chosen:
        text = texts.submitted_text(med)
        assert text is not None
        for r in range(plan.smoke_repetitions):
            calls.append(ScheduledCall(
                call_id=_call_id("smoke", plan.seed, Condition.SMOKE, med, None, r), block=0, order=-1,
                service=Service.ACM, condition=Condition.SMOKE, role=Role.SMOKE, group_id=row.group_id,
                medication=med, repetition=r, profile=None, input_text=text,
                input_sha256=sha256_text(text), parent=None))
    rng.shuffle(calls)
    calls = [replace(c, order=i) for i, c in enumerate(calls)]
    schedule = Schedule("smoke", plan.seed, plan_sha256, manifest_sha256, tuple(calls), tuple(excluded))
    check_schedule(schedule, plan)
    return schedule


def _allocate(sizes: dict[str, int], total: int) -> dict[str, int]:
    """Proportional allocation by largest remainder (ties by stratum name), capped at stratum sizes."""
    alloc: dict[str, int] = {}
    free = dict(sizes)
    budget = total
    while free:
        pop = sum(free.values())
        exact = {s: budget * n / pop for s, n in free.items()}
        capped = [s for s in free if exact[s] >= free[s]]
        if capped:
            for s in capped:
                alloc[s] = free.pop(s)
                budget -= alloc[s]
            continue
        base = {s: math.floor(x) for s, x in exact.items()}
        extra = budget - sum(base.values())
        for s in sorted(free, key=lambda s: (-(exact[s] - base[s]), s))[:extra]:
            base[s] += 1
        alloc.update(base)
        break
    return alloc


def plan_pilot(rows: Sequence[ManifestRow], manifest_sha256: str, plan: Plan, plan_sha256: str,
               texts: TextSource) -> Schedule:
    open_rows = open_groups(rows, ["dev", "cal"])
    strata: dict[str, list[ManifestRow]] = defaultdict(list)
    for row in sorted(open_rows, key=lambda r: r.group_id):
        strata[row.stratum].append(row)
    if plan.pilot_texts > len(open_rows):
        raise ValueError(f"pilot needs {plan.pilot_texts} groups, only {len(open_rows)} in dev/cal")
    quota = _allocate({s: len(g) for s, g in strata.items()}, plan.pilot_texts)

    excluded: list[tuple[int, str]] = []
    chosen: list[tuple[ManifestRow, int]] = []
    for stratum in sorted(strata):
        order = list(strata[stratum])
        _rng(plan.seed, "stratum", stratum).shuffle(order)
        taken = 0
        for row in order:
            if taken == quota[stratum]:
                break
            med = _representative(row, texts, True, excluded)
            if med is not None:
                chosen.append((row, med))
                taken += 1
        if taken < quota[stratum]:
            raise ValueError(f"stratum {stratum!r}: {taken} eligible groups for a quota of {quota[stratum]}")

    reps = plan.pilot_repetitions
    per_block: dict[int, list[ScheduledCall]] = defaultdict(list)
    for row, med in chosen:
        acm_text = texts.submitted_text(med)
        pt_text = texts.pt_indication(med)
        assert acm_text is not None and pt_text is not None
        acm_roles = _roles(plan, med, None)
        for r in range(reps):
            block = r * plan.pilot_blocks // reps
            per_block[block].append(ScheduledCall(
                call_id=_call_id("pilot", plan.seed, Condition.ACM_ISOLATED, med, None, r), block=block,
                order=-1, service=Service.ACM, condition=Condition.ACM_ISOLATED, role=acm_roles[r],
                group_id=row.group_id, medication=med, repetition=r, profile=None, input_text=acm_text,
                input_sha256=sha256_text(acm_text), parent=None))
        for profile in plan.profiles:
            roles = _roles(plan, med, profile.name)
            for r in range(reps):
                block = r * plan.pilot_blocks // reps
                tid = _call_id("pilot", plan.seed, Condition.TRANSLATION_ISOLATED, med, profile.name, r)
                per_block[block].append(ScheduledCall(
                    call_id=tid, block=block, order=-1, service=Service.TRANSLATE,
                    condition=Condition.TRANSLATION_ISOLATED, role=roles[r], group_id=row.group_id,
                    medication=med, repetition=r, profile=profile.name, input_text=pt_text,
                    input_sha256=sha256_text(pt_text), parent=None))
                per_block[block].append(ScheduledCall(
                    call_id=_call_id("pilot", plan.seed, Condition.FULL_PIPELINE, med, profile.name, r),
                    block=block, order=-1, service=Service.ACM, condition=Condition.FULL_PIPELINE,
                    role=roles[r], group_id=row.group_id, medication=med, repetition=r,
                    profile=profile.name, input_text=None, input_sha256=None, parent=tid))

    calls: list[ScheduledCall] = []
    for block in sorted(per_block):
        shuffled = list(per_block[block])
        _rng(plan.seed, "order", block).shuffle(shuffled)
        calls.extend(_children_after_parents(shuffled))
    calls = [replace(c, order=i) for i, c in enumerate(calls)]
    schedule = Schedule("pilot", plan.seed, plan_sha256, manifest_sha256, tuple(calls), tuple(excluded))
    check_schedule(schedule, plan)
    return schedule


def _roles(plan: Plan, med: int, profile: str | None) -> list[Role]:
    """Fixed before collection: a seeded permutation of the slots picks the reference repetitions."""
    slots = list(range(plan.pilot_repetitions))
    _rng(plan.seed, "roles", med, profile or "").shuffle(slots)
    refs = set(slots[:plan.pilot_references])
    return [Role.REFERENCE if r in refs else Role.EVALUATION for r in range(plan.pilot_repetitions)]


def _children_after_parents(calls: list[ScheduledCall]) -> list[ScheduledCall]:
    """Move each FULL_PIPELINE call whose parent comes later to right after its parent."""
    position = {c.call_id: i for i, c in enumerate(calls)}
    moved: dict[str, list[ScheduledCall]] = defaultdict(list)
    stay: list[ScheduledCall] = []
    for i, c in enumerate(calls):
        if c.parent is not None and position[c.parent] > i:
            moved[c.parent].append(c)
        else:
            stay.append(c)
    out: list[ScheduledCall] = []
    for c in stay:
        out.append(c)
        out.extend(moved.pop(c.call_id, []))
    return out


def check_schedule(schedule: Schedule, plan: Plan) -> None:
    """Verify the §9.2-9.3 design constraints; raise ScheduleError on the first violation."""
    calls = schedule.calls
    ids = [c.call_id for c in calls]
    if len(set(ids)) != len(ids):
        raise ScheduleError("duplicate call_id")
    orders = [c.order for c in calls]
    if len(set(orders)) != len(orders):
        raise ScheduleError("duplicate order")
    by_id = {c.call_id: c for c in calls}
    for c in calls:
        if c.parent is None:
            continue
        p = by_id.get(c.parent)
        if p is None:
            raise ScheduleError(f"{c.call_id}: unknown parent")
        if p.order >= c.order:
            raise ScheduleError(f"{c.call_id}: parent does not precede child")
        if p.condition is not Condition.TRANSLATION_ISOLATED or c.condition is not Condition.FULL_PIPELINE:
            raise ScheduleError(f"{c.call_id}: a parent must be a translation feeding a full-pipeline call")
        if (c.role, c.block, c.profile, c.repetition, c.medication) != (
                p.role, p.block, p.profile, p.repetition, p.medication):
            raise ScheduleError(f"{c.call_id}: does not inherit role/block/profile/repetition from parent")
    if schedule.kind != "pilot":
        return

    for block in range(plan.pilot_blocks):
        in_block = [c for c in calls if c.block == block]
        missing = {Condition.ACM_ISOLATED, Condition.TRANSLATION_ISOLATED,
                   Condition.FULL_PIPELINE} - {c.condition for c in in_block}
        if missing:
            raise ScheduleError(f"block {block} lacks conditions {sorted(missing)}")
        if {c.role for c in in_block} != {Role.REFERENCE, Role.EVALUATION}:
            raise ScheduleError(f"block {block} does not contain both roles")
    units: dict[tuple[int, str | None], list[ScheduledCall]] = defaultdict(list)
    for c in calls:
        if c.condition is Condition.ACM_ISOLATED:
            units[(c.medication, None)].append(c)
        elif c.condition is Condition.TRANSLATION_ISOLATED:
            units[(c.medication, c.profile)].append(c)
    for key, members in units.items():
        if sorted(c.repetition for c in members) != list(range(plan.pilot_repetitions)):
            raise ScheduleError(f"unit {key}: repetitions are not 0..{plan.pilot_repetitions - 1}")
        n_ref = sum(c.role is Role.REFERENCE for c in members)
        if n_ref != plan.pilot_references:
            raise ScheduleError(f"unit {key}: {n_ref} references, expected {plan.pilot_references}")
