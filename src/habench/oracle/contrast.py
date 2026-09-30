"""The contrast of SPEC §5.1: one document group, two executed runs, the declared configs and `D`.

A contrast is truth-side material: it holds the executed levels, the variants κ0/κ1 (SPEC 4.3) and the
patch contents. Methods never see it; views are built from it by the scenario code.

Conventions:
- `x0`/`x1` are executed `Config`s. A patch `p` of the contrast appears as the item `patch:p` with
  `False` in x0 and `True` in x1 (the edited response is the x1 response, SPEC 4.5).
- `d0`/`d1` are the declared configs: post-ACM factors only, never patches (SPEC 4.5).
- `variants0`/`variants1` list only the factors whose variant is `alt`; every other factor is `std`.
- `bundles` maps a declared bundle name (a member of `D`) to its component factors (SPEC 4.4).
- `prep_available` lists, for contrasts with preparation factors in `D`, the prep subsets that have a
  stored response (SPEC 5.3); `()` and the full prep set are always available.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from habench.pipeline import catalog
from habench.pipeline.catalog import Config, Level
from habench.pipeline.evidence import JsonEdit, Patch

MAX_FACTORS = 6
SPACES = ("who", "cm")
VARIANT_LEVELS: dict[str, tuple[str, ...] | None] = {
    # factor -> levels that have an `alt` variant (None: every level), SPEC 4.3
    "ent_thr": None,
    "icd_thr": None,
    "trait": ("v1",),
    "occ": ("last_upsert",),
    "map": ("cm_gated",),
}


def has_alt(f: str, level: Level) -> bool:
    if f not in VARIANT_LEVELS:
        return False
    levels = VARIANT_LEVELS[f]
    return levels is None or level in levels


def _stage(f: str) -> str:
    return catalog.factor(f).stage


@dataclass(frozen=True)
class Contrast:
    cid: str
    group: str
    meds: tuple[int, ...]
    space: str
    x0: Config
    x1: Config
    d0: Config
    d1: Config
    D: tuple[str, ...]
    variants0: frozenset[str] = frozenset()
    variants1: frozenset[str] = frozenset()
    patches: tuple[Patch, ...] = ()
    bundles: tuple[tuple[str, tuple[str, ...]], ...] = ()
    prep_available: tuple[tuple[str, ...], ...] = ()
    _hash: str = field(default="", init=False, repr=False, compare=False)

    # ------------------------------------------------------------------ derived views

    @property
    def patch_map(self) -> dict[str, Patch]:
        return {p.id: p for p in self.patches}

    @property
    def bundle_map(self) -> dict[str, tuple[str, ...]]:
        return dict(self.bundles)

    def components(self, f: str) -> tuple[str, ...]:
        """Config factors switched by the member `f` of D (a bundle switches all its components)."""
        return self.bundle_map.get(f, (f,))

    @property
    def prep_factors(self) -> tuple[str, ...]:
        return tuple(f for f in self.D if f not in self.bundle_map and _stage(f) == "prep")

    def variant(self, run: int, f: str) -> str:
        return "alt" if f in (self.variants1 if run else self.variants0) else "std"

    def executed_diff(self) -> frozenset[str]:
        """Config factors whose executed (level, variant) differs between x0 and x1 (SPEC 5.1)."""
        a, b = self.x0.as_dict(), self.x1.as_dict()
        return frozenset(
            n for n in a.keys() | b.keys()
            if (a.get(n), self.variant(0, n)) != (b.get(n), self.variant(1, n))
        )

    # ------------------------------------------------------------------ validation

    def validate(self, *, check_sealed: bool = True) -> None:
        """Raise ValueError on an inconsistent contrast and SealedError for a test-partition group."""
        if check_sealed:
            from habench.data import splits

            splits.check_not_sealed(self.meds)
        if self.space not in SPACES:
            raise ValueError(f"unknown space {self.space!r}")
        if not self.meds or list(self.meds) != sorted(set(self.meds)):
            raise ValueError("meds must be non-empty, sorted and unique")
        if len(self.D) > MAX_FACTORS:
            raise ValueError(f"|D| = {len(self.D)} > {MAX_FACTORS}")
        if len(set(self.D)) != len(self.D) or list(self.D) != sorted(self.D):
            raise ValueError("D must be sorted and unique")
        for n, _ in self.d0.items + self.d1.items:
            if n.startswith("patch:"):
                raise ValueError("declared configs never contain patches (SPEC 4.5)")
        for run, variants in ((self.x0, self.variants0), (self.x1, self.variants1)):
            for f in variants:
                if not has_alt(f, run.get(f)):
                    raise ValueError(f"no `alt` variant for {f}={run.get(f)!r} (SPEC 4.3)")
        ids = [p.id for p in self.patches]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate patch ids")
        for p in self.patches:
            if self.x0.get(p.factor) is not False or self.x1.get(p.factor) is not True:
                raise ValueError(f"{p.factor} must be False in x0 and True in x1")
            if p.factor not in self.D:
                raise ValueError(f"{p.factor} must be in D")
            if not p.meds <= set(self.meds):
                raise ValueError(f"{p.factor} edits medications outside the group")
        covered: set[str] = set()
        for f in self.D:
            if f in self.bundle_map:
                comps = self.bundle_map[f]
                if not comps or any(_stage(c) != "post" for c in comps):
                    raise ValueError(f"bundle {f} must have post-ACM components")
                covered |= set(comps)
            elif f.startswith("patch:"):
                if f[len("patch:"):] not in self.patch_map:
                    raise ValueError(f"{f} has no patch content")
                covered.add(f)
            elif _stage(f) == "prep":
                pass
            elif _stage(f) == "post":
                covered.add(f)
            else:
                raise ValueError(f"factor {f} (stage {_stage(f)}) cannot be in D")
        comps_all = [c for b in self.bundle_map.values() for c in b]
        if len(comps_all) != len(set(comps_all)):
            raise ValueError("bundles overlap")
        if set(self.bundle_map) - set(self.D):
            raise ValueError("every bundle must be a member of D")
        diff = self.executed_diff()
        if diff != covered:
            raise ValueError(
                f"D does not match the executed diff: missing {sorted(diff - covered)}, "
                f"extra {sorted(covered - diff)}"
            )
        prep = set(self.prep_factors)
        for sub in self.prep_available:
            if not set(sub) <= prep or list(sub) != sorted(set(sub)):
                raise ValueError(f"prep_available entry {sub} is not a sorted subset of the prep factors")

    # ------------------------------------------------------------------ serialization

    def to_json(self) -> dict:
        return {
            "cid": self.cid,
            "group": self.group,
            "meds": list(self.meds),
            "space": self.space,
            "x0": _config_json(self.x0),
            "x1": _config_json(self.x1),
            "d0": _config_json(self.d0),
            "d1": _config_json(self.d1),
            "D": list(self.D),
            "variants0": sorted(self.variants0),
            "variants1": sorted(self.variants1),
            "patches": [_patch_json(p) for p in sorted(self.patches, key=lambda p: p.id)],
            "bundles": [[n, list(c)] for n, c in sorted(self.bundles)],
            "prep_available": [list(s) for s in sorted(self.prep_available)],
        }

    @classmethod
    def from_json(cls, obj: Mapping) -> Contrast:
        return cls(
            cid=obj["cid"],
            group=obj["group"],
            meds=tuple(obj["meds"]),
            space=obj["space"],
            x0=_config_from(obj["x0"]),
            x1=_config_from(obj["x1"]),
            d0=_config_from(obj["d0"]),
            d1=_config_from(obj["d1"]),
            D=tuple(obj["D"]),
            variants0=frozenset(obj.get("variants0", ())),
            variants1=frozenset(obj.get("variants1", ())),
            patches=tuple(_patch_from(p) for p in obj.get("patches", ())),
            bundles=tuple((n, tuple(c)) for n, c in obj.get("bundles", ())),
            prep_available=tuple(tuple(s) for s in obj.get("prep_available", ())),
        )

    def canonical(self) -> str:
        return canonical_json(self.to_json())

    def content_hash(self) -> str:
        """SHA-256 of the canonical JSON (hex)."""
        if not self._hash:
            object.__setattr__(self, "_hash", hashlib.sha256(self.canonical().encode("utf-8")).hexdigest())
        return self._hash


def canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _config_json(c: Config) -> list:
    return [[n, v] for n, v in c.items]


def _config_from(items: Iterable) -> Config:
    return Config.of({n: v for n, v in items})


def _patch_json(p: Patch) -> dict:
    return {"id": p.id, "edits": [{"med": e.med, "path": list(e.path), "value": e.value} for e in p.edits]}


def _patch_from(obj: Mapping) -> Patch:
    return Patch(obj["id"], tuple(JsonEdit(e["med"], tuple(e["path"]), e["value"]) for e in obj["edits"]))


def make_contrast(
    cid: str,
    group: str,
    meds: Iterable[int],
    space: str,
    x0: Config,
    x1: Config,
    *,
    d0: Config | None = None,
    d1: Config | None = None,
    variants0: Iterable[str] = (),
    variants1: Iterable[str] = (),
    patches: Iterable[Patch] = (),
    bundles: Mapping[str, Iterable[str]] | None = None,
    prep: Iterable[str] = (),
    prep_available: Iterable[Iterable[str]] = (),
    check_sealed: bool = True,
) -> Contrast:
    """Build and validate a contrast. Patches are added to x1 (True) and x0 (False); D is derived:
    bundles, then the remaining executed diff, then patches and prep factors."""
    patches = tuple(patches)
    x0 = x0.with_items({p.factor: False for p in patches})
    x1 = x1.with_items({p.factor: True for p in patches})
    bundles = {n: tuple(sorted(c)) for n, c in (bundles or {}).items()}
    draft = Contrast(cid, group, tuple(sorted(set(meds))), space, x0, x1, d0 or _declared(x0), d1 or _declared(x1),
                     (), frozenset(variants0), frozenset(variants1), patches)
    diff = draft.executed_diff()
    in_bundles = {c for comps in bundles.values() for c in comps}
    D = sorted(set(bundles) | (diff - in_bundles) | set(prep))
    c = Contrast(
        draft.cid, draft.group, draft.meds, space, x0, x1, draft.d0, draft.d1, tuple(D),
        draft.variants0, draft.variants1, patches, tuple(sorted(bundles.items())),
        tuple(sorted(tuple(sorted(s)) for s in prep_available)),
    )
    c.validate(check_sealed=check_sealed)
    return c


def _declared(x: Config) -> Config:
    return Config.of({n: v for n, v in x.items if not n.startswith("patch:")})
