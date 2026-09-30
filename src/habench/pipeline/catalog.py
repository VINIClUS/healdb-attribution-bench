"""Factor catalog, configurations and presets (design §B1).

Post-ACM factors act on stored responses and can be enumerated as hybrids. Prep and ACM factors
are catalogued with `available=False`: without a stored response for the changed input there is
no counterfactual (protocol §7.3). A `patch:<id>` factor is binary (False = original evidence,
True = semisynthetic edit applied).

Hybrid semantics that the design leaves open are fixed here (see the level docstrings):
- `occ=per_entity_any` with `sel=all`: one record per (entity Id, concept code), as V2's
  `entity_icd` rows; with `sel=top1` this is one record per entity Id, as V2's `cutoff_audit`.
- `sel=top1` under `occ=last_upsert`: top-1 candidates are emitted in the order of their entity's
  first occurrence, then grouped by code with the last one setting the scores.
- `occ=first_upsert`: the first occurrence sets scalars and trait scores (an INSERT IGNORE variant).
- `map=who_exact`: exact subcategory or exact 3-char category, no prefix fallback.
- extra `trait` levels: see TRAIT_RULES.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Level = str | float | bool
Stage = Literal["prep", "acm", "post", "patch"]


@dataclass(frozen=True, slots=True)
class Factor:
    name: str
    stage: Stage
    levels: tuple[Level, ...]
    available: bool  # hybrids can be enumerated from stored responses
    description: str


@dataclass(frozen=True, slots=True)
class TraitRule:
    """Record-level trait and type rule.

    veto: trait names whose presence (any score) rejects the record.
    hyp_veto_gt: reject when a HYPOTHETICAL trait scores above this (None: no rule); a missing score counts as 0.
    required: when set, at least one trait must be in this set or be HYPOTHETICAL with score <= hyp_ok_le.
    entity_type: when set, the record's entity Type must equal it.
    """

    veto: frozenset[str]
    hyp_veto_gt: float | None
    required: frozenset[str] | None
    hyp_ok_le: float | None
    entity_type: str | None


_V1_VETO = frozenset({"LOW_CONFIDENCE", "NEGATION", "PERTAINS_TO_FAMILY"})
_V1_REQUIRED = frozenset({"DIAGNOSIS", "SYMPTOM", "SIGN"})

TRAIT_RULES: dict[str, TraitRule] = {
    # link@405a10c lines 134-148 as executed (HYPOTHETICAL rejected above 0.65).
    "v1": TraitRule(_V1_VETO, 0.65, _V1_REQUIRED, 0.6, None),
    # V2 HEAD: NEGATION veto (score ignored) and Type = DX_NAME.
    "v2": TraitRule(frozenset({"NEGATION"}), None, None, None, "DX_NAME"),
    # V1 as documented in the header (line 24): HYPOTHETICAL accepted only at <= 0.6.
    "v1_hyp_le_0.6": TraitRule(_V1_VETO, 0.6, _V1_REQUIRED, 0.6, None),
    # V1 without the required-trait clause.
    "v1_no_required": TraitRule(_V1_VETO, 0.65, None, None, None),
    # NEGATION veto only, no type rule.
    "neg_only": TraitRule(frozenset({"NEGATION"}), None, None, None, None),
}

# map level -> (output system, WHO policy used for the gate or None, WHO policy used for projection)
MAP_LEVELS: dict[str, tuple[str, str | None, str]] = {
    "cm_gated": ("cm", "v1_gate", "exact_fb"),  # V1: dotted CM code kept if the hierarchy gate passes
    "cm_ungated": ("cm", None, "exact_fb"),  # extend (inferred): no gate
    "who_exact_fb": ("who", "exact_fb", "exact_fb"),  # V2: exact subcategory, else 3-char category, else drop
    "who_exact": ("who", "exact", "exact"),
    "who_cat3": ("who", "cat3", "cat3"),
}

FACTORS: dict[str, Factor] = {
    f.name: f
    for f in (
        Factor("occ", "post", ("last_upsert", "per_entity_any", "first_upsert"), True,
               "occurrence rule: V1 upsert on (med, CM code) with the last occurrence setting scores and traits "
               "unioned; V2 decides each entity Id alone, presence = any, score = MAX"),
        Factor("sel", "post", ("all", "top1"), True,
               "concept selection before occ: every concept, or the rank-1 concept per entity Id "
               "(score desc, code asc)"),
        Factor("ent_thr", "post", (0.60, 0.70, 0.55, 0.65), True, "entity Score >= t"),
        Factor("icd_thr", "post", (0.60, 0.30, 0.55, 0.65), True, "concept Score >= t"),
        Factor("trait", "post", tuple(TRAIT_RULES), True, "trait veto, HYPOTHETICAL rule, required traits, Type"),
        Factor("map", "post", tuple(MAP_LEVELS), True, "hierarchy gate, projection and output code system"),
        Factor("dup_ind", "prep", (True, False), False, "indication sent twice (V1) or once (V2)"),
        Factor("mask_drug", "prep", (False, True), False, "drug name replaced by <drug>"),
        Factor("wow_rewrite", "prep", (False, True), False, "'with or without' rewritten as 'regardless of'"),
        Factor("cut10k", "prep", (True, False), False, "text cut at 10,000 characters"),
        Factor("translation", "prep", ("stored",), False, "PT->EN translation realization"),
        Factor("acm_model", "acm", ("stored",), False, "ACM call and returned ModelVersion"),
    )
}

# Attribute knobs: never part of D for presence targets.
ATTRIBUTE_KNOBS: dict[str, float] = {"low_conf_thr": 0.70, "icd_hi": 0.60}

POST_FACTORS = ("occ", "sel", "ent_thr", "icd_thr", "trait", "map")
THRESHOLDS = frozenset({"ent_thr", "icd_thr"})


def factor(name: str) -> Factor:
    if name.startswith("patch:"):
        return Factor(name, "patch", (False, True), True, "semisynthetic evidence edit")
    return FACTORS[name]


@dataclass(frozen=True, slots=True)
class Config:
    """An executed (or declared) configuration: sorted (factor, level) items."""

    items: tuple[tuple[str, Level], ...]

    def __post_init__(self) -> None:
        names = [n for n, _ in self.items]
        if names != sorted(set(names)):
            raise ValueError("Config items must be sorted and unique; use Config.of(...)")
        for n, v in self.items:
            f = factor(n)
            if n in THRESHOLDS:
                # listed levels are the catalogued grid; any threshold in [0, 1] is admissible
                if isinstance(v, bool) or not isinstance(v, float) or not 0.0 <= v <= 1.0:
                    raise ValueError(f"threshold {n} must be a float in [0, 1], got {v!r}")
            elif f.stage == "post" and v not in f.levels:
                raise ValueError(f"unknown level {v!r} for factor {n}")

    @classmethod
    def of(cls, mapping: dict[str, Level]) -> Config:
        return cls(tuple(sorted(mapping.items())))

    def as_dict(self) -> dict[str, Level]:
        return dict(self.items)

    def get(self, name: str, default: Level | None = None) -> Level | None:
        return self.as_dict().get(name, default)

    def __getitem__(self, name: str) -> Level:
        return self.as_dict()[name]

    def with_(self, **kw: Level) -> Config:
        d = self.as_dict()
        d.update(kw)
        return Config.of(d)

    def with_items(self, mapping: dict[str, Level]) -> Config:
        d = self.as_dict()
        d.update(mapping)
        return Config.of(d)

    def diff(self, other: Config) -> frozenset[str]:
        a, b = self.as_dict(), other.as_dict()
        return frozenset(n for n in a.keys() | b.keys() if a.get(n) != b.get(n))

    def patches_on(self) -> frozenset[str]:
        return frozenset(n[len("patch:"):] for n, v in self.items if n.startswith("patch:") and v)


def hybrid(x0: Config, x1: Config, S: frozenset[str]) -> Config:
    """x0 with the factors in S set to their x1 levels."""
    extra = S - x0.diff(x1)
    if extra:
        raise ValueError(f"factors not in the contrast diff: {sorted(extra)}")
    b = x1.as_dict()
    return x0.with_items({n: b[n] for n in S})


V1 = Config.of({"occ": "last_upsert", "sel": "all", "ent_thr": 0.60, "icd_thr": 0.60, "trait": "v1", "map": "cm_gated"})
V2 = Config.of({"occ": "per_entity_any", "sel": "top1", "ent_thr": 0.70, "icd_thr": 0.30, "trait": "v2",
                "map": "who_exact_fb"})
V1_EXTEND = V1.with_(map="cm_ungated")

# Declared bundles (design §B1).
V1_TO_V2 = (V1, V2)  # D = {occ, sel, ent_thr, icd_thr, trait, map}
EXTEND = (V1, V1_EXTEND)  # D = {map}
