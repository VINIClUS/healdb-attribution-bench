"""Scenario generation (SPEC 12, T9): contrasts plus sampled queries for the families N, F, M, O, X and I.

`generate(partition, seed=...)` returns the scenarios; `generate_with_report` also returns the
`GenerationReport` (counts produced, dropped by reason, ineligible queries, generation errors). Only dev and cal
are generated: any request for "test" raises `SealedError` before evidence is touched. Family P is catalogued
only (repro/scenario_catalog.yaml) and never generated; the crossing of I(a) with views and capabilities is the
runner's job.

Determinism: the seed and stable sha256 hashes drive every choice; groups are processed in group-id order, so
the same seed gives identical scenarios (compare `scenarios_canonical`).
"""

from __future__ import annotations

import csv
import dataclasses
from collections.abc import Iterable, Sequence

from habench.data import splits
from habench.pipeline.evidence import Evidence
from habench.pipeline.mapping import Hierarchy
from habench.scenarios import families as fam
from habench.scenarios import xfamily
from habench.scenarios.base import Assessed, Ctx, GenerationReport, Scenario, take
from habench.scenarios.config import ScenarioConfig, load_config
from habench.scenarios.levels import check_partition
from habench.oracle.contrast import canonical_json

Group = tuple[str, tuple[int, ...]]


def manifest_groups(partition: str) -> list[Group]:
    """(group id, medications) of the groups of `partition` in repro/split_manifest.csv (';'-separated meds)."""
    check_partition(partition)
    with open(splits.MANIFEST_PATH, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["partition"] == partition]
    return sorted((r["group_id"], tuple(sorted(int(m) for m in r["medications"].split(";")))) for r in rows)


def scenarios_canonical(scenarios: Iterable[Scenario]) -> str:
    return canonical_json([s.to_json() for s in scenarios])


def _finish(a: Assessed) -> Scenario:
    """The scenario of an accepted candidate; M scenarios also flag granularity changes (SPEC 2.1)."""
    sc = a.scenario
    if sc.family != "M":
        return sc
    h = a.hybrids
    n = fam.granularity_changes(list(a.sample.changed), h.run(frozenset()).present,
                                h.run(frozenset(h.D)).present)
    return dataclasses.replace(sc, notes=(*sc.notes, f"granularity changes (ancestor relation): {n}"))


def _group(ctx: Ctx, quota: xfamily.ShapeQuota) -> list[Scenario]:
    cfg = ctx.cfg
    acc: list[Assessed] = []
    acc += take(ctx, fam.n_candidates(ctx), int(cfg.family("N")["targets_per_group"]), null=True)
    F = cfg.family("F")
    border = take(ctx, fam.f_border(ctx), int(F["border_max"]))
    acc += border
    acc += take(ctx, fam.f_plain(ctx), int(F["targets_per_group"]) - len(border))
    acc += take(ctx, fam.m_candidates(ctx), int(cfg.family("M")["targets_per_group"]))
    acc += take(ctx, fam.o_candidates(ctx), int(cfg.family("O")["targets_per_group"]))
    X = cfg.family("X")
    acc += take(ctx, xfamily.x_bundle(ctx), int(X["i_bundle"]))
    acc += take(ctx, xfamily.x_components(ctx), int(X["i_components"]))
    acc += xfamily.sample_x_ii(ctx, quota, int(X["ii"]))
    acc += take(ctx, xfamily.x_ex07(ctx), int(X["iii"]))
    I = cfg.family("I")
    for kind in list(I["declared_kinds"])[: int(I["declared_per_group"])]:
        acc += take(ctx, fam.i_declared(ctx, kind), 1)
    for kind in list(I["alt_kinds"])[: int(I["alt_per_group"])]:
        acc += take(ctx, fam.i_alt(ctx, kind), 1)
    return [_finish(a) for a in acc]


def generate_with_report(
    partition: str,
    *,
    seed: int,
    groups: Sequence[Group] | None = None,
    evidence: Evidence | None = None,
    hier: Hierarchy | None = None,
    max_groups: int | None = None,
    config: ScenarioConfig | None = None,
) -> tuple[list[Scenario], GenerationReport]:
    check_partition(partition)  # SealedError for "test", before any data is touched
    cfg = config or load_config()
    chosen = sorted(groups if groups is not None else manifest_groups(partition), key=lambda g: g[0])
    if max_groups is not None:
        chosen = chosen[:max_groups]
    meds = sorted({m for _, ms in chosen for m in ms})
    splits.check_not_sealed(meds)
    if evidence is None:
        from habench.pipeline.evidence import load_evidence

        evidence = load_evidence("v1", meds)
    if hier is None:
        from habench.pipeline.mapping import load_hierarchy

        hier = load_hierarchy("v1")
    report = GenerationReport()
    quota = xfamily.ShapeQuota(dict(cfg.family("X")["shape_quota"]))
    out: list[Scenario] = []
    seen: set[str] = set()
    for gid, gmeds in chosen:
        ctx = Ctx(partition, seed, gid, tuple(sorted(gmeds)), evidence.subset(gmeds), hier, cfg, report)
        for sc in _group(ctx, quota):
            if sc.contrast.cid in seen:
                report.drop(sc.family, "duplicate_cid")
                continue
            seen.add(sc.contrast.cid)
            report.produced[f"{sc.family}/{sc.subfamily}"] += 1
            out.append(sc)
    return out, report


def generate(
    partition: str,
    *,
    seed: int,
    groups: Sequence[Group] | None = None,
    evidence: Evidence | None = None,
    hier: Hierarchy | None = None,
    max_groups: int | None = None,
) -> list[Scenario]:
    return generate_with_report(partition, seed=seed, groups=groups, evidence=evidence, hier=hier,
                                max_groups=max_groups)[0]
