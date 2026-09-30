"""One parameterized, deterministic post-ACM pipeline over stored responses (design §B2).

Order: patches -> candidates in array order -> `sel` -> `occ` records -> record predicates
(`map` gate, `trait`, `icd_thr`, `ent_thr`) -> projection to the key space -> presence and attributes.
Presets `catalog.V1` and `catalog.V2` reproduce the historical tables (tests `-m dumps`).

Records depend only on (evidence, sel, occ) and are cached on the evidence; predicates are numpy
masks, so the 2^6 hybrids of a contrast share the expensive part.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from habench.pipeline import catalog, mapping
from habench.pipeline.catalog import Config, TraitRule
from habench.pipeline.evidence import STATUS_FAILED, STATUS_MISSING, Evidence, Patch, collation_key
from habench.pipeline.mapping import Hierarchy
from habench.pipeline.trace import CandRow, Decision, RecordRow, Trace
from habench.types import SYSTEM_ICD10_WHO, SYSTEM_ICD10CM, AssocKey, Presence

# Predicate stages, in V1 code order (link@405a10c 111-148); used by `funnel` and traces.
STAGES = ("map", "trait_veto", "trait_hyp", "scores", "trait_required", "trait_type")


@dataclass(frozen=True, slots=True)
class KeySpace:
    """Comparison space: native ICD-10-CM keys ("cm") or WHO ICD-10 keys ("who").

    In "who", ICD-10-CM outputs are projected by exact subcategory + 3-char fallback: a structural
    projection, not a validated terminology translation (protocol §5.1).
    """

    kind: str

    def __post_init__(self) -> None:
        if self.kind not in ("cm", "who"):
            raise ValueError(f"unknown key space {self.kind!r}")


CM = KeySpace("cm")
WHO = KeySpace("who")


@dataclass(eq=False)
class Records:
    med: np.ndarray
    code: np.ndarray  # index into ev.codes
    eid: np.ndarray  # -1 for code-keyed records
    es: np.ndarray
    cs: np.ndarray
    etype: np.ndarray  # index into ev.types
    source: np.ndarray  # candidate that set the scalars
    members: list[tuple[int, ...]]
    traits: list[dict[str, float | None]]
    selected: np.ndarray  # bool per candidate: kept by `sel`

    def __len__(self) -> int:
        return len(self.med)


@dataclass(frozen=True, slots=True)
class Attrs:
    """Attributes of a present key: MAX concept score and the entity score of the best record
    (concept score desc, entity score desc), as V2's dedup; for V1 CM keys there is one record."""

    score: float
    entity_score: float


@dataclass(frozen=True)
class RunResult:
    config: Config
    space: KeySpace
    present: frozenset[AssocKey]
    attrs: Mapping[AssocKey, Attrs]
    unmapped: frozenset[tuple[int, str]]  # (med, CM code) of passing records without a key in the space
    status: Mapping[int, str]
    trace: Trace | None = None

    def state(self, key: AssocKey) -> Presence:
        st = self.status[key.med]
        if st in (STATUS_FAILED, STATUS_MISSING):
            return Presence.UNAVAILABLE
        return Presence.PRESENT if key in self.present else Presence.ABSENT


# ---------------------------------------------------------------- records (sel, occ)


def _entity_eid(ev: Evidence) -> np.ndarray:
    return ev.e_eid[ev.c_ent] if len(ev.c_ent) else np.zeros(0, dtype=np.int64)


def _select(ev: Evidence, sel: str) -> list[int]:
    """Candidate ids kept by `sel`: emission order for `all`; for `top1`, one winner per Id group in the order of
    the group's first candidate (not emission order, SPEC 3.2 step 3, EX-29)."""
    n = len(ev.c_med)
    if sel == "all":
        return list(range(n))
    if sel != "top1":
        raise ValueError(f"unknown sel level {sel!r}")
    eid = _entity_eid(ev)
    groups: dict[tuple[int, int], dict[int, int]] = {}  # (med, eid) -> code -> last candidate
    for c in range(n):
        groups.setdefault((int(ev.c_med[c]), int(eid[c])), {})[int(ev.c_code[c])] = c
    out = []
    for rows in groups.values():  # first-appearance order of the entity Id
        best = min(rows.values(), key=lambda c: (-ev.c_cs[c], collation_key(ev.codes[ev.c_code[c]])))
        out.append(best)
    return out


def records(ev: Evidence, sel: str, occ: str) -> Records:
    key = ("records", sel, occ)
    if key in ev._cache:
        return ev._cache[key]
    cands = _select(ev, sel)
    selected = np.zeros(len(ev.c_med), dtype=bool)
    selected[cands] = True
    eid = _entity_eid(ev)
    groups: dict[tuple, list[int]] = {}
    if occ in ("last_upsert", "first_upsert"):
        for c in cands:
            groups.setdefault((int(ev.c_med[c]), int(ev.c_code[c])), []).append(c)
    elif occ == "per_entity_any":
        for c in cands:
            groups.setdefault((int(ev.c_med[c]), int(eid[c]), int(ev.c_code[c])), []).append(c)
    else:
        raise ValueError(f"unknown occ level {occ!r}")

    ent_traits: dict[tuple[int, int], dict[str, float | None]] = {}
    if occ == "per_entity_any":
        for e in range(len(ev.e_med)):  # V2 entity_trait: upsert on (med, entity Id, name), all occurrences
            d = ent_traits.setdefault((int(ev.e_med[e]), int(ev.e_eid[e])), {})
            for name, score in ev.e_traits[e]:
                d[name] = score

    n = len(groups)
    med = np.empty(n, dtype=np.int64)
    code = np.empty(n, dtype=np.int64)
    reid = np.full(n, -1, dtype=np.int64)
    source = np.empty(n, dtype=np.int64)
    members: list[tuple[int, ...]] = []
    traits: list[dict[str, float | None]] = []
    first = occ == "first_upsert"
    for i, (gk, cs_) in enumerate(groups.items()):
        src = cs_[0] if first else cs_[-1]
        med[i], code[i], source[i] = gk[0], gk[-1], src
        members.append(tuple(cs_))
        if occ == "per_entity_any":
            reid[i] = gk[1]
            traits.append(ent_traits.get((gk[0], gk[1]), {}))
        else:
            d: dict[str, float | None] = {}
            for c in cs_:
                for name, score in ev.e_traits[ev.c_ent[c]]:
                    if first and name in d:
                        continue
                    d[name] = score
            traits.append(d)
    rec = Records(
        med=med, code=code, eid=reid,
        es=ev.c_es[source] if n else np.zeros(0), cs=ev.c_cs[source] if n else np.zeros(0),
        etype=ev.c_type[source] if n else np.zeros(0, dtype=np.int64),
        source=source, members=members, traits=traits, selected=selected,
    )
    ev._cache[key] = rec
    return rec


# ---------------------------------------------------------------- predicates


def _trait_masks(ev: Evidence, rec: Records, level: str) -> dict[str, np.ndarray]:
    key = ("trait", id(rec), level)
    if key in ev._cache:
        return ev._cache[key]
    rule: TraitRule = catalog.TRAIT_RULES[level]
    n = len(rec)
    veto = np.ones(n, dtype=bool)
    hyp = np.ones(n, dtype=bool)
    req = np.ones(n, dtype=bool)
    for i, d in enumerate(rec.traits):
        if rule.veto and not rule.veto.isdisjoint(d):
            veto[i] = False
        h = d.get("HYPOTHETICAL", "absent")
        if rule.hyp_veto_gt is not None and h != "absent" and (h or 0) > rule.hyp_veto_gt:
            hyp[i] = False
        if rule.required is not None:
            ok = any(
                name in rule.required or (name == "HYPOTHETICAL" and (s or 0) <= rule.hyp_ok_le)
                for name, s in d.items()
            )
            req[i] = ok
    if rule.entity_type is None:
        typ = np.ones(n, dtype=bool)
    else:
        want = [i for i, t in enumerate(ev.types) if t == rule.entity_type]
        typ = np.isin(rec.etype, want)
    out = {"trait_veto": veto, "trait_hyp": hyp, "trait_required": req, "trait_type": typ}
    ev._cache[key] = out
    return out


def _code_map(ev: Evidence, hier: Hierarchy, level: str, space: KeySpace) -> tuple[np.ndarray, list[str | None]]:
    """Per code index: gate verdict and key code in `space` (None = unmapped)."""
    key = ("map", hier.sha256, level, space.kind)
    if key in ev._cache:
        return ev._cache[key]
    system, gate, proj = catalog.MAP_LEVELS[level]
    if system == "who" and space.kind == "cm":
        raise ValueError(f"map level {level} produces WHO ICD-10 codes; it has no ICD-10-CM key space")
    ok = np.empty(len(ev.codes), dtype=bool)
    target: list[str | None] = []
    for i, code in enumerate(ev.codes):
        if gate is None:
            ok[i] = True
        elif gate == "v1_gate":
            ok[i] = mapping.v1_gate(hier, code)
        else:
            ok[i] = mapping.who_map(hier, code, gate)[0] is not None
        if space.kind == "cm":
            target.append(code)
        else:
            target.append(mapping.who_map(hier, code, proj)[0])
    ev._cache[key] = (ok, target)
    return ok, target


@dataclass(eq=False)
class Evaluated:
    """Records of one configuration with every stage mask (all evaluated, not short-circuited)."""

    config: Config
    evidence: Evidence
    records: Records
    masks: dict[str, np.ndarray]  # stage -> passes
    passed: np.ndarray


def evaluate(cfg: Config, ev: Evidence, hier: Hierarchy, patches: Mapping[str, Patch] | None = None) -> Evaluated:
    on = cfg.patches_on()
    if on:
        missing = on - set(patches or {})
        if missing:
            raise KeyError(f"unknown patches: {sorted(missing)}")
        ev = ev.patched(patches[p] for p in on)  # type: ignore[index]
    rec = records(ev, str(cfg["sel"]), str(cfg["occ"]))
    gate, _ = _code_map(ev, hier, str(cfg["map"]), WHO)
    masks = {"map": gate[rec.code] if len(rec) else np.zeros(0, dtype=bool)}
    masks.update(_trait_masks(ev, rec, str(cfg["trait"])))
    masks["icd_thr"] = rec.cs >= float(cfg["icd_thr"])
    masks["ent_thr"] = rec.es >= float(cfg["ent_thr"])
    passed = np.ones(len(rec), dtype=bool)
    for m in masks.values():
        passed &= m
    return Evaluated(cfg, ev, rec, masks, passed)


def funnel(e: Evaluated, order: tuple[str, ...] = STAGES) -> list[tuple[str, int]]:
    """Survivor counts after applying the stages sequentially ("scores" = icd_thr and ent_thr)."""
    alive = np.ones(len(e.records), dtype=bool)
    out = [("records", int(alive.sum()))]
    for st in order:
        m = e.masks["icd_thr"] & e.masks["ent_thr"] if st == "scores" else e.masks[st]
        alive &= m
        out.append((st, int(alive.sum())))
    return out


# ---------------------------------------------------------------- projection and run


def _keys(ev: Evidence, hier: Hierarchy, rec: Records, level: str, space: KeySpace) -> tuple[np.ndarray, list[AssocKey]]:
    key = ("keys", id(rec), hier.sha256, level, space.kind)
    if key in ev._cache:
        return ev._cache[key]
    _, target = _code_map(ev, hier, level, space)
    table: dict[tuple[int, str], int] = {}
    objs: list[AssocKey] = []
    kidx = np.full(len(rec), -1, dtype=np.int64)
    for i in range(len(rec)):
        t = target[rec.code[i]]
        if t is None:
            continue
        m = int(rec.med[i])
        k = (m, t)
        j = table.get(k)
        if j is None:
            j = table[k] = len(objs)
            if space.kind == "cm":
                objs.append(AssocKey(m, SYSTEM_ICD10CM, f"acm:{ev.model_version(m)}", t))
            else:
                objs.append(AssocKey(m, SYSTEM_ICD10_WHO, hier.version, t))
        kidx[i] = j
    ev._cache[key] = (kidx, objs)
    return kidx, objs


def run(
    cfg: Config,
    ev: Evidence,
    hier: Hierarchy,
    space: KeySpace = WHO,
    *,
    patches: Mapping[str, Patch] | None = None,
    trace: bool = False,
    trace_meds: frozenset[int] | None = None,
) -> RunResult:
    e = evaluate(cfg, ev, hier, patches)
    rec, pev = e.records, e.evidence
    kidx, objs = _keys(pev, hier, rec, str(cfg["map"]), space)
    idx = np.flatnonzero(e.passed)
    mapped = idx[kidx[idx] >= 0]
    unmapped = frozenset((int(rec.med[i]), pev.codes[rec.code[i]]) for i in idx[kidx[idx] < 0])
    # best record per key: concept score desc, entity score desc
    order = np.lexsort((-rec.es[mapped], -rec.cs[mapped], kidx[mapped]))
    best = mapped[order]
    ks = kidx[best]
    first = np.ones(len(ks), dtype=bool)
    first[1:] = ks[1:] != ks[:-1]
    attrs = {objs[k]: Attrs(float(rec.cs[i]), float(rec.es[i])) for k, i in zip(ks[first], best[first])}
    tr = _trace(e, kidx, objs, trace_meds) if trace else None
    return RunResult(
        config=cfg,
        space=space,
        present=frozenset(attrs),
        attrs=attrs,
        unmapped=unmapped,
        status={m: pev.info[m].status for m in pev.meds},
        trace=tr,
    )


def _reason(stage: str, e: Evaluated, i: int) -> str:
    cfg, rec, ev = e.config, e.records, e.evidence
    ok = bool(e.masks[stage][i])
    if stage == "icd_thr":
        return f"cs {rec.cs[i]!r} {'>=' if ok else '<'} {cfg['icd_thr']}"
    if stage == "ent_thr":
        return f"es {rec.es[i]!r} {'>=' if ok else '<'} {cfg['ent_thr']}"
    if stage == "map":
        return f"{cfg['map']}: {ev.codes[rec.code[i]]} {'passes' if ok else 'fails'} the hierarchy gate"
    rule = catalog.TRAIT_RULES[str(cfg["trait"])]
    names = sorted(rec.traits[i])
    if stage == "trait_veto":
        hit = sorted(rule.veto & set(names))
        return f"vetoed by {hit}" if hit else "no vetoed trait"
    if stage == "trait_hyp":
        return (f"HYPOTHETICAL {rec.traits[i].get('HYPOTHETICAL')!r} > {rule.hyp_veto_gt}" if not ok
                else "HYPOTHETICAL rule passes")
    if stage == "trait_required":
        return "has a required trait" if ok else f"no required trait among {names}"
    return f"type {ev.types[rec.etype[i]]} {'==' if ok else '!='} {rule.entity_type}"


def _trace(e: Evaluated, kidx: np.ndarray, objs: list[AssocKey], meds: frozenset[int] | None) -> Trace:
    ev, rec = e.evidence, e.records
    wanted = frozenset(ev.meds) if meds is None else meds
    eid = _entity_eid(ev)
    cands = tuple(
        CandRow(
            cid=c, med=int(ev.c_med[c]), pos=int(ev.e_pos[ev.c_ent[c]]), eid=int(eid[c]),
            code=ev.codes[ev.c_code[c]], rank=int(ev.c_rank[c]), es=float(ev.c_es[c]), cs=float(ev.c_cs[c]),
            tp=ev.types[ev.c_type[c]], traits=ev.e_traits[ev.c_ent[c]], selected=bool(rec.selected[c]),
        )
        for c in range(len(ev.c_med)) if int(ev.c_med[c]) in wanted
    )
    rows, decisions = [], []
    stages = ("map", "trait_veto", "trait_hyp", "icd_thr", "ent_thr", "trait_required", "trait_type")
    for i in range(len(rec)):
        if int(rec.med[i]) not in wanted:
            continue
        rows.append(RecordRow(
            rid=i, med=int(rec.med[i]), code=ev.codes[rec.code[i]],
            eid=None if rec.eid[i] < 0 else int(rec.eid[i]), members=rec.members[i], source=int(rec.source[i]),
            es=float(rec.es[i]), cs=float(rec.cs[i]), tp=ev.types[rec.etype[i]],
            traits=tuple(sorted(rec.traits[i].items(), key=lambda t: collation_key(t[0]))),
            key=objs[kidx[i]] if kidx[i] >= 0 else None,
        ))
        decisions.extend(Decision(i, st, bool(e.masks[st][i]), _reason(st, e, i)) for st in stages)
    return Trace(tuple(sorted(wanted)), cands, tuple(rows), tuple(decisions))
