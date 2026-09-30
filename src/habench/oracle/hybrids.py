"""Hybrid execution of a contrast through the core (SPEC 5.2-5.4).

`h_S` runs `pipeline.core.run` on the group's evidence with the members of `S` at their x1 (level,
variant) and every other factor at x0's. One run serves every association of the group, and runs are
cached by the realized configuration, so two `S` that realize the same config share one run (SPEC 7.4).

Variants (SPEC 4.3) are realized as core levels: `alt` of a threshold is `> t` (`>= nextafter(t)`),
`trait=v1` alt is `v1_hyp_le_0.6`, `occ=last_upsert` alt is `first_upsert`, `map=cm_gated` alt is
`cm_ungated`.

`levels="executed"` is the truth (and a broker with the code link); `levels="declared"` replays with
d0/d1 as a broker without the code link (SPEC 5.4), keeping each run's variants.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from itertools import combinations

import numpy as np

from habench.pipeline import catalog, core
from habench.pipeline.catalog import Config, Level
from habench.pipeline.core import CM, WHO, RunResult
from habench.pipeline.evidence import Evidence
from habench.pipeline.mapping import Hierarchy
from habench.oracle.contrast import Contrast, has_alt
from habench.types import AssocKey, Presence

ALT_LEVEL = {"trait": {"v1": "v1_hyp_le_0.6"}, "occ": {"last_upsert": "first_upsert"}, "map": {"cm_gated": "cm_ungated"}}


class Inadmissible(ValueError):
    """The hybrid has no stored response for its preparation combination (SPEC 5.3)."""


def realize(f: str, level: Level, variant: str) -> Level:
    """The core level that implements (level, variant) of factor f."""
    if variant != "alt" or not has_alt(f, level):
        return level  # levels without an `alt` variant behave as `std` (SPEC 4.3)
    if f in catalog.THRESHOLDS:
        return float(np.nextafter(float(level), 2.0))
    return ALT_LEVEL[f][level]


def all_subsets(D: Iterable[str]) -> list[frozenset[str]]:
    """Subsets of D by size, then lexicographic order of the sorted names."""
    names = sorted(D)
    return [frozenset(s) for k in range(len(names) + 1) for s in combinations(names, k)]


class Hybrids:
    def __init__(
        self,
        contrast: Contrast,
        evidence: Evidence,
        hier: Hierarchy,
        *,
        levels: str = "executed",
        prep_evidence: Mapping[tuple[str, ...], Evidence] | None = None,
        cache: dict | None = None,
    ) -> None:
        """`cache`: an optional run cache shared by several `Hybrids` over the same evidence objects (runs are
        keyed by evidence identity, space and realized config)."""
        if levels not in ("executed", "declared"):
            raise ValueError(levels)
        self.contrast = c = contrast
        self.hier = hier
        self.levels = levels
        self.space = WHO if c.space == "who" else CM
        self.evidence = evidence if tuple(evidence.meds) == c.meds else evidence.subset(c.meds)
        self._prep = {(): self.evidence, **dict(prep_evidence or {})}
        patch_items_0 = {p.factor: False for p in c.patches}
        patch_items_1 = {p.factor: True for p in c.patches}
        if levels == "executed":
            self.base0, self.base1 = c.x0, c.x1
            self.D = c.D
        else:
            self.base0 = c.d0.with_items(patch_items_0)
            self.base1 = c.d1.with_items(patch_items_1)
            self.D = self._declared_D()
        self._cache: dict[tuple, RunResult] = {} if cache is None else cache
        self.runs = 0  # distinct core runs executed

    def _declared_D(self) -> tuple[str, ...]:
        c = self.contrast
        diff = self.base0.diff(self.base1)
        bundles = c.bundle_map
        out = {b for b, comps in bundles.items() if set(comps) & diff}
        in_bundles = {x for comps in bundles.values() for x in comps}
        out |= {f for f in diff if f not in in_bundles}
        out |= set(c.prep_factors)
        return tuple(sorted(out))

    # ------------------------------------------------------------------ admissibility and configs

    def prep_key(self, S: Iterable[str]) -> tuple[str, ...]:
        prep = set(self.contrast.prep_factors)
        return tuple(sorted(set(S) & prep))

    def admissible(self, S: Iterable[str]) -> bool:
        """SPEC 5.3: post and patch factors are always admissible; prep needs a stored response."""
        return self.prep_key(S) in self._prep

    def config(self, S: Iterable[str]) -> Config:
        """The realized core config of h_S (levels from catalog.hybrid, variants from each level's run)."""
        S = frozenset(S)
        extra = S - set(self.D)
        if extra:
            raise ValueError(f"not in D: {sorted(extra)}")
        c = self.contrast
        switched = {x for f in S for x in c.components(f)}
        level_diff = self.base0.diff(self.base1)
        cfg = catalog.hybrid(self.base0, self.base1, frozenset(switched & level_diff))
        realized = {}
        for f, level in cfg.items:
            if f.startswith("patch:") or catalog.factor(f).stage != "post":
                continue
            v = c.variant(1 if f in switched else 0, f)
            if v == "alt":
                realized[f] = realize(f, level, v)
        return cfg.with_items(realized) if realized else cfg

    # ------------------------------------------------------------------ runs

    def run(self, S: Iterable[str], *, trace: bool = False) -> RunResult:
        S = frozenset(S)
        if not self.admissible(S):
            raise Inadmissible(sorted(S))
        cfg = self.config(S)
        pk = self.prep_key(S)
        key = (self._prep[pk], self.space.kind, cfg.items)  # Evidence hashes by identity and stays alive
        hit = self._cache.get(key)
        if hit is not None and (hit.trace is not None or not trace):
            return hit
        res = core.run(cfg, self._prep[pk], self.hier, self.space, patches=self.contrast.patch_map, trace=trace)
        if hit is None:
            self.runs += 1
        self._cache[key] = res
        return res

    def state(self, S: Iterable[str], key: AssocKey) -> Presence:
        return self.run(S).state(key)

    def truth_table(self, key: AssocKey) -> dict[frozenset[str], Presence]:
        """state_S(key) for every admissible S ⊆ D."""
        return {S: self.state(S, key) for S in all_subsets(self.D) if self.admissible(S)}

    def endpoints_reproduce(self) -> bool:
        """SPEC 5.4: h_∅ and h_D realize the recorded x0 and x1 (checked on the executed levels)."""
        c = self.contrast
        ok0 = self.config(frozenset()) == _realized_run(c, 0)
        ok1 = self.config(frozenset(self.D)) == _realized_run(c, 1)
        return ok0 and ok1


def _realized_run(c: Contrast, run: int) -> Config:
    x = c.x1 if run else c.x0
    realized = {
        f: realize(f, level, c.variant(run, f))
        for f, level in x.items
        if not f.startswith("patch:") and catalog.factor(f).stage == "post" and c.variant(run, f) == "alt"
    }
    return x.with_items(realized) if realized else x
