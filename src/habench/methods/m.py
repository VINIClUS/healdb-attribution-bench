"""Method M (protocol §10; design §D; SPEC §4.3, §5.4, §6.3, §8, §9.2).

Per contrast:
1. **Inventory.** Which artifact kinds the view shows, the declared configs, the executed configs (only with the
   code link), the parsed responses (full or top-1) and the stored traces (L2-M).
2. **Declared ≠ executed.** With the code link, compare declared and executed levels (noted). Without it, the
   broker replays the declared levels (SPEC 5.4), so M enumerates the testable level-divergence hypotheses of
   SPEC 4.3 on the declared diff — x0 ran the x1 level (`on`: the handle is always switched) or x1 ran the x0
   level (`off`: never switched), at most 3 per hypothesis — and keeps those whose replayed endpoints reproduce
   the observed finals (and the stored traces, when visible).
3. **Search.** For each consistent hypothesis, the joint reference BFS (SPEC 6.3) over the remaining handles,
   with sound dummy pruning from the visible responses.
4. **Identification-aware output.** One family over every consistent hypothesis → `explicacao_verificada` with
   `final`/`eval`/`dummy` certificates; distinct families → `alternativas`. A factor whose level or variant could
   differ invisibly and could matter for the association (`evidence_rules.pair_irrelevant`) makes the answer
   ambiguous: `informacao_insuficiente` under `rigor="strict"`, ignored under `rigor="lenient"` (the knob swept
   in cal, SPEC 13.5).
5. **Without replay** (R-C, or nothing runnable): a changed association is explained only when every member of D
   but one is certified irrelevant (`final` + `dummy` cover the whole lattice, SPEC 9.2 step 3).

L3 controls: the deterministic core has no reference realizations (L3 ≡ L2, SPEC 7.1), so M never outputs
`compativel_com_variabilidade`; with references it would compare the target pair against them first.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations, product

from habench.methods.base import (
    AMBIGUIDADE,
    EVIDENCIA_OCULTA,
    INADMISSIBLE,
    ORCAMENTO,
    REPLAY_INVALIDO,
    SEM_RESPOSTA_ARMAZENADA,
    BudgetExhausted,
    Certificate,
    Env,
    EvalResult,
    Explanation,
    Query,
    Unavailable,
    abstain,
    canonical_family,
    canonical_set,
    final_certificates,
    presence,
    same_presence,
    validated,
)
from habench.methods.evidence_rules import ALT_LEVELS, PAIRS, THRESHOLDS, Evidence, MedDoc
from habench.methods.search import SearchResult, bfs
from habench.types import AssocKey, OutputState, Presence

MAX_DIVERGENT = 3  # SPEC 4.3: at most 3 factors with a divergent level or alt variant per history
PREP = frozenset({"dup_ind", "mask_drug", "wow_rewrite", "cut10k", "translation"})  # prep factors (SPEC 4.1)
TRAIT_STAGES = {"trait_veto", "trait_hyp", "trait_required", "trait_type"}


def has_alt(f: str, level: str | None) -> bool:
    return level is not None and (f in THRESHOLDS or (f, level) in ALT_LEVELS)


# ---------------------------------------------------------------------- inventory


TraceSig = frozenset[tuple]  # comparable summary of a run's trace


@dataclass(frozen=True)
class Inventory:
    kinds: frozenset[str]
    cfg: tuple[Mapping[str, str], Mapping[str, str]]
    executed: tuple[Mapping[str, str], Mapping[str, str]] | None  # None: no code link
    evidence: Evidence | None
    traces: tuple[TraceSig, TraceSig] | None  # stored x0/x1 traces (L2-M), as signatures
    full_traces: bool  # `trace` (every record) rather than `trace_winners`
    responses_differ: bool  # the x0 and x1 ACM responses differ (hashes or visible responses)

    def notes(self) -> tuple[str, ...]:
        out = ["inventory:" + ",".join(sorted(self.kinds))]
        if self.executed is not None:
            diverging = sorted(
                n for r in (0, 1) for n in self.cfg[r].keys() | self.executed[r].keys()
                if self.cfg[r].get(n) != self.executed[r].get(n)
            )
            out.append("declared_config:" + ("refutado:" + ",".join(dict.fromkeys(diverging)) if diverging else "armazenado"))
        return tuple(out)


def _read_json(env: Env, kind: str, run: str):
    refs = [r for r in env.artifacts() if r.kind == kind and r.run == run]
    return json.loads(env.read(refs[0])) if refs else None


def _stages_failed(stages: Sequence[tuple[str, bool]]) -> frozenset[str]:
    return frozenset("trait" if s in TRAIT_STAGES else s for s, ok in stages if not ok)


def _key(k) -> tuple | None:
    return None if k is None else tuple(k)


def trace_signature(records: Sequence[tuple[int, str, tuple | None, bool, frozenset[str]]], full: bool) -> TraceSig:
    """Full traces compare every record's (med, code, key, failed); winners compare the approved records only."""
    if full:
        return frozenset((med, code, key, failed) for med, code, key, _, failed in records)
    return frozenset((med, code, key) for med, code, key, ok, _ in records if ok)


def _stored_trace(obj, full: bool) -> TraceSig | None:
    if obj is None:
        return None
    if full:
        if "records" not in obj:  # N1/N2 historical tables: not comparable with a hybrid trace
            return None
        by_rid: dict[int, list[tuple[str, bool]]] = {}
        for d in obj["decisions"]:
            by_rid.setdefault(d["ref"], []).append((d["stage"], d["verdict"]))
        recs = []
        for r in obj["records"]:
            failed = _stages_failed(by_rid.get(r["rid"], []))
            recs.append((r["med"], r["code"], _key(r["key"]), not failed, failed))
        return trace_signature(recs, True)
    return trace_signature([(w["record"]["med"], w["record"]["code"], _key(w["record"]["key"]), True, frozenset())
                            for w in obj], False)


def _eval_signature(res: EvalResult, full: bool) -> TraceSig:
    return trace_signature(
        [(t.med, t.code, None if t.key is None else (t.key.med, t.key.system, t.key.version, t.key.code),
          t.verdict, frozenset(t.failed)) for t in res.trace],
        full,
    )


def inventory(env: Env) -> Inventory:
    kinds = frozenset(r.kind for r in env.artifacts())
    cfg = (env.config("x0"), env.config("x1"))
    try:
        executed = (env.executed_config("x0"), env.executed_config("x1"))
    except Unavailable:
        executed = None
    evidence = None
    for kind, top1 in (("acm_response", False), ("acm_response_top1", True)):
        if kind in kinds:
            r0, r1 = _read_json(env, kind, "x0"), _read_json(env, kind, "x1")
            if r0 is None or r1 is None:
                continue
            meds = {int(m) for m in r0} | {int(m) for m in r1}
            evidence = Evidence(
                {m: MedDoc.parse(r0.get(str(m)), top1=top1) for m in meds},
                {m: MedDoc.parse(r1.get(str(m)), top1=top1) for m in meds},
                {m: r0.get(str(m)) == r1.get(str(m)) for m in meds},
            )
            break
    traces, full = None, False
    for kind, is_full in (("trace", True), ("trace_winners", False)):
        if kind in kinds:
            t0 = _stored_trace(_read_json(env, kind, "x0"), is_full)
            t1 = _stored_trace(_read_json(env, kind, "x1"), is_full)
            if t0 is not None and t1 is not None:
                traces, full = (t0, t1), is_full
            break
    differ = evidence is not None and not all(evidence.raw_equal.values())
    if "hashes" in kinds:
        h0, h1 = _read_json(env, "hashes", "x0"), _read_json(env, "hashes", "x1")
        differ = differ or (h0 or {}).get("acm_response") != (h1 or {}).get("acm_response")
    return Inventory(kinds, cfg, executed, evidence, traces, full, differ)


# ---------------------------------------------------------------------- hypotheses


@dataclass(frozen=True, slots=True)
class Hypothesis:
    on: frozenset[str] = frozenset()  # x0 ran the x1 declared level: always switched in the replay
    off: frozenset[str] = frozenset()  # x1 ran the x0 declared level: never switched

    def label(self) -> str:
        return f"on={sorted(self.on)} off={sorted(self.off)}"


def hypotheses(inv: Inventory, D: Sequence[str]) -> list[Hypothesis]:
    """The declared-levels history first, then every testable divergence combination (≤ MAX_DIVERGENT)."""
    if inv.executed is not None:
        return [Hypothesis()]
    c0, c1 = inv.cfg
    options: list[list[tuple[str, str]]] = []
    for f in D:
        opts = []
        if PAIRS.get((f, c0.get(f))) == c1.get(f) and c1.get(f) is not None:
            opts.append((f, "on"))
        if PAIRS.get((f, c1.get(f))) == c0.get(f) and c0.get(f) is not None:
            opts.append((f, "off"))
        if opts:
            options.append(opts)
    out = [Hypothesis()]
    for k in range(1, min(MAX_DIVERGENT, len(options)) + 1):
        for group in combinations(options, k):
            for pick in product(*group):
                out.append(Hypothesis(frozenset(f for f, s in pick if s == "on"), frozenset(f for f, s in pick if s == "off")))
    return out


# ---------------------------------------------------------------------- the method


@dataclass(frozen=True)
class M:
    rigor: str = "strict"  # "strict" | "lenient"
    name: str = "m"

    def explain(self, env: Env, queries: Sequence[Query]) -> Mapping[str, Explanation]:
        inv = inventory(env)
        notes = inv.notes()
        D = tuple(sorted(env.factors()))
        f0, f1 = env.final("x0"), env.final("x1")
        out: dict[str, Explanation] = {}
        open_q: list[Query] = []
        for q in queries:
            s0, s1 = presence(f0, q.key), presence(f1, q.key)
            if Presence.UNAVAILABLE in (s0, s1):
                out[q.qid] = abstain(q.qid, OutputState.INFORMACAO_INSUFICIENTE, EVIDENCIA_OCULTA, *notes)
            elif s0 == s1:
                out[q.qid] = abstain(q.qid, OutputState.AUSENCIA_DE_MUDANCA, "", *notes)
            else:
                open_q.append(q)
        if open_q and inv.responses_differ and not any(h.startswith("ev:") or h in PREP for h in D):
            # The responses changed but no handle can change them (e.g. L1 hides patch handles): an unseen
            # evidence factor is in D, so no family over the visible handles can be claimed.
            out |= {q.qid: abstain(q.qid, OutputState.INFORMACAO_INSUFICIENTE, EVIDENCIA_OCULTA, *notes,
                                   "responses differ without an evidence handle") for q in open_q}
        elif open_q:
            out |= self._changed(env, inv, D, open_q, notes)
        return {k: validated(v) for k, v in out.items()}

    # ------------------------------------------------------------------ helpers

    def _levels(self, inv: Inventory, f: str) -> tuple[str, str] | None:
        src = inv.executed or inv.cfg
        if f in src[0] and f in src[1]:
            return src[0][f], src[1][f]
        return None

    def _dummies(self, inv: Inventory, D: Sequence[str], key: AssocKey) -> frozenset[str]:
        if inv.evidence is None:
            return frozenset()
        patches = frozenset(h for h in D if h.startswith("ev:"))
        return frozenset(f for f in D if inv.evidence.dummy(f, key, self._levels(inv, f), patches))

    def _effective(self, inv: Inventory, D: Sequence[str]) -> tuple[str, ...]:
        """Members of D that can differ in the executed runs, as far as the view shows (for the no-replay path)."""
        if inv.executed is None:
            return tuple(D)
        e0, e1 = inv.executed
        return tuple(h for h in D if h.startswith("ev:") or h not in e0 or h not in e1 or e0[h] != e1[h])

    def _hidden(self, inv: Inventory, D: Sequence[str], key: AssocKey, replay: bool) -> list[str]:
        """Factors whose level/variant may differ invisibly between the runs and may matter for `key`."""
        if replay and inv.executed is not None:
            return []  # the broker replays executed levels with the real variants (SPEC 5.4)
        src = inv.executed or inv.cfg
        names = sorted(set(src[0]) | set(src[1]))
        effective = set(self._effective(inv, D))
        out = []
        for g in names:
            lv0, lv1 = src[0].get(g), src[1].get(g)
            if replay:
                # Variants are realized by the broker; only untestable level divergences remain (SPEC 4.3).
                risky = [lv for r, lv in ((0, lv0), (1, lv1)) if (g, lv) in PAIRS
                         and not (g in D and PAIRS[(g, lv)] == (lv1 if r == 0 else lv0))]
            elif inv.executed is not None:
                if g in effective:
                    continue
                risky = [lv for lv in (lv0, lv1) if has_alt(g, lv)]
            else:
                if g in THRESHOLDS and g in effective:
                    continue
                risky = [lv for lv in (lv0, lv1) if has_alt(g, lv) or (g, lv) in PAIRS]
            if any(inv.evidence is None or not inv.evidence.pair_irrelevant(g, lv, key) for lv in set(risky)):
                out.append(g)
        return out

    def _ambiguous(self, qid: str, inv: Inventory, hidden: list[str], notes: tuple[str, ...]) -> Explanation:
        reason = EVIDENCIA_OCULTA if inv.evidence is None else AMBIGUIDADE
        return abstain(qid, OutputState.INFORMACAO_INSUFICIENTE, reason, *notes, "hidden:" + ",".join(hidden))

    def _no_replay(self, inv: Inventory, D: Sequence[str], q: Query, notes: tuple[str, ...]) -> Explanation:
        hidden = self._hidden(inv, D, q.key, replay=False)
        if hidden and self.rigor == "strict":
            return self._ambiguous(q.qid, inv, hidden, notes)
        eff = self._effective(inv, D)
        Z = self._dummies(inv, eff, q.key)
        rest = [f for f in eff if f not in Z]
        if len(rest) != 1:
            reason = EVIDENCIA_OCULTA if inv.evidence is None else AMBIGUIDADE
            return abstain(q.qid, OutputState.INFORMACAO_INSUFICIENTE, reason, *notes)
        certs = final_certificates(D) + tuple(Certificate("dummy", (f,), True) for f in sorted(Z))
        return Explanation(q.qid, OutputState.EXPLICACAO_VERIFICADA, (((rest[0],),),), certs, notes=notes)

    # ------------------------------------------------------------------ changed associations

    def _changed(self, env: Env, inv: Inventory, D: tuple[str, ...], qs: list[Query], notes) -> dict[str, Explanation]:
        if env.capability() == "R-C":
            return {q.qid: self._no_replay(inv, D, q, notes) for q in qs}
        f0, f1 = env.final("x0"), env.final("x1")
        out: dict[str, Explanation] = {}
        live: list[Query] = []
        for q in qs:
            hidden = self._hidden(inv, D, q.key, replay=True)
            if hidden and self.rigor == "strict":
                out[q.qid] = self._ambiguous(q.qid, inv, hidden, notes)
            else:
                live.append(q)
        if not live:
            return out

        consistent: list[Hypothesis] = []
        try:
            for h in hypotheses(inv, D):
                r0, r1 = env.evaluate(h.on), env.evaluate(frozenset(D) - h.off)
                if not (same_presence(r0.presence, f0) and same_presence(r1.presence, f1)):
                    continue
                if inv.traces is not None and (
                    _eval_signature(r0, inv.full_traces) != inv.traces[0]
                    or _eval_signature(r1, inv.full_traces) != inv.traces[1]
                ):
                    continue
                consistent.append(h)
        except BudgetExhausted:
            return out | {q.qid: abstain(q.qid, OutputState.ORCAMENTO_ESGOTADO, ORCAMENTO, *notes) for q in live}
        except Unavailable:
            return out | {q.qid: self._no_replay(inv, D, q, notes) for q in live}
        if not consistent:
            return out | {q.qid: abstain(q.qid, OutputState.INFORMACAO_INSUFICIENTE, REPLAY_INVALIDO, *notes)
                          for q in live}
        hyp_notes = notes + tuple("hypothesis:" + h.label() for h in consistent if h != Hypothesis())

        keys = {q.qid: q.key for q in live}
        dummies = {q.qid: self._dummies(inv, D, q.key) for q in live}
        runs: list[tuple[Hypothesis, SearchResult]] = []
        for h in consistent:
            members = [f for f in D if f not in h.on and f not in h.off]
            try:
                res = bfs(lambda s, on=h.on: env.evaluate(s | on), members, keys, dummies)
            except BudgetExhausted:
                return out | {q.qid: abstain(q.qid, OutputState.ORCAMENTO_ESGOTADO, ORCAMENTO, *hyp_notes) for q in live}
            runs.append((h, res))
        for q in live:
            out[q.qid] = self._decide(q, inv, D, runs, dummies[q.qid], hyp_notes)
        return out

    def _decide(self, q: Query, inv: Inventory, D, runs, Z: frozenset[str], notes) -> Explanation:
        fams: dict[tuple, list[tuple[Hypothesis, SearchResult]]] = {}
        for h, res in runs:
            if res.exhausted:
                return abstain(q.qid, OutputState.ORCAMENTO_ESGOTADO, ORCAMENTO, *notes)
            if q.qid in res.unchanged:
                continue  # this history does not change the association: it cannot be the true one
            if not res.complete[q.qid]:
                if INADMISSIBLE in res.unknown.values():
                    return abstain(q.qid, OutputState.CONTRAFACTUAL_INDISPONIVEL, SEM_RESPOSTA_ARMAZENADA, *notes)
                fallback = self._no_replay(inv, D, q, notes)  # e.g. N1/N2: S not expressible
                if fallback.state == OutputState.EXPLICACAO_VERIFICADA:
                    return fallback
                return abstain(q.qid, OutputState.INFORMACAO_INSUFICIENTE, AMBIGUIDADE, *notes)
            fams.setdefault(res.families[q.qid], []).append((h, res))
        if not fams:
            return abstain(q.qid, OutputState.INFORMACAO_INSUFICIENTE, REPLAY_INVALIDO, *notes)
        if len(fams) >= 2:
            return Explanation(q.qid, OutputState.ALTERNATIVAS, tuple(sorted(fams)), notes=notes)
        (family, support), = fams.items()
        certs = final_certificates(D) + tuple(Certificate("dummy", (f,), True) for f in sorted(Z))
        if len(support) == 1:
            h, res = support[0]
            target = res.results[frozenset(D) - h.off - h.on].state(q.key)
            certs += tuple(
                Certificate("eval", canonical_set(s | h.on), r.state(q.key) == target)
                for s, r in res.results.items()
            )
        return Explanation(q.qid, OutputState.EXPLICACAO_VERIFICADA, (canonical_family(family),), certs, notes=notes)


@dataclass(frozen=True)
class MLenient(M):
    """M with `rigor="lenient"`, addressable as "habench.methods.m:MLenient" for the cal sweep (SPEC 13.5)."""

    rigor: str = "lenient"
    name: str = "m_lenient"
