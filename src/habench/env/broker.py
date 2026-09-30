"""The evaluation broker (SPEC §5.3-5.4, §7.1-7.4, §11.1): a trusted-process `Env` over the core.

`BrokerEnv` replays hybrids through `oracle.hybrids.Hybrids` and applies the budget, cache and refusal rules of
`env.table.Ledger`. It lives in the trusted process; the method process talks to it through `env.rpc`.

Handles and members. `Hybrids` works on members of D (`ent_thr`, a bundle name, `patch:p1`, a prep factor); methods
see handles: the same names, except that each patch member is exposed as the opaque `ev:<hmac8>` handle recorded in
`BrokerSide.handles`. The Ledger works on handles; the callbacks translate to members.

Replay (SPEC 5.4, 7.2): executed levels with the code link, declared levels without. For A2 views (top-1 concept
only) the replay runs over evidence whose every entity keeps its first listed concept, rebuilt from the original
raw responses; patch edits that touch a removed concept (`ICD10CMConcepts` at index >= 1) are dropped
(`dropped_edits` records how many per patch), so the degraded replay may fail to validate, which is what A2 measures.
The truth-side finals always come from the executed levels on the full evidence, and are free.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from habench.env.table import Ledger
from habench.methods.base import (
    NOT_EXPRESSIBLE,
    NOT_VISIBLE,
    ArtifactRef,
    ContrastInfo,
    EvalResult,
    Meter,
    PresenceMap,
    TraceRecord,
    Unavailable,
)
from habench.oracle.contrast import Contrast
from habench.oracle.hybrids import Hybrids
from habench.oracle.truth import CellSpec, default_expressible, split_view
from habench.pipeline.evidence import STATUS_FAILED, STATUS_MISSING, Evidence, JsonEdit, Patch
from habench.pipeline.mapping import Hierarchy
from habench.pipeline.core import RunResult
from habench.pipeline.trace import Trace
from habench.types import SYSTEM_ICD10_WHO, SYSTEM_ICD10CM, AssocKey, Presence
from habench.views.layout import BrokerSide, public_config, read_manifest

RUNS = ("x0", "x1")

_TRAIT_STAGES = frozenset({"trait_veto", "trait_hyp", "trait_required", "trait_type"})


def expressible(view: str, hybrids: Hybrids, S: Iterable[str]) -> bool:
    """Whether the set S of D members can be replayed in the historical code of an N1/N2 view (SPEC 7.1).

    Delegates to `oracle.truth.default_expressible` on the hybrids actually replayed, so the broker's refusals and
    the truth's budget necessity share one rule (patches stay expressible there: they are evidence edits).
    """
    return default_expressible(CellSpec.of(view, "R-C"), hybrids, frozenset(S))  # only the view matters


# ---------------------------------------------------------------------- top-1 evidence (A2)


def _truncate_response(text: str | None) -> str | None:
    if text is None:
        return None
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return text
    entities = doc.get("Entities") if isinstance(doc, dict) else None
    if not isinstance(entities, list):
        return text
    for ent in entities:
        if isinstance(ent, dict) and isinstance(ent.get("ICD10CMConcepts"), list):
            ent["ICD10CMConcepts"] = ent["ICD10CMConcepts"][:1]
    return json.dumps(doc)


def _touches_removed_concept(edit: JsonEdit) -> bool:
    path = edit.path
    for i, step in enumerate(path):
        if step == "ICD10CMConcepts":
            return i + 1 < len(path) and isinstance(path[i + 1], int) and path[i + 1] >= 1
    return False


def _filter_patch(p: Patch) -> tuple[Patch, int]:
    """The patch without its edits on removed concepts (a whole-list edit keeps its first concept)."""
    kept: list[JsonEdit] = []
    for e in p.edits:
        if _touches_removed_concept(e):
            continue
        if e.path and e.path[-1] == "ICD10CMConcepts" and isinstance(e.value, list):
            e = JsonEdit(e.med, e.path, e.value[:1])
        kept.append(e)
    return Patch(p.id, tuple(kept)), len(p.edits) - len(kept)


def top1_evidence(ev: Evidence, patches: Iterable[Patch] = ()) -> Evidence:
    """`ev` rebuilt from its original raw responses with every entity's concepts cut to the first one."""
    base = ev._cache.get("_base", ev)
    raw = {med: _truncate_response(text) for med, text in base._raw.items()}
    top = Evidence.from_responses(raw.items(), meds=ev.meds)
    kept = [_filter_patch(p)[0] for p in (*ev.patches, *patches)]
    return top.patched(kept) if kept else top


# ---------------------------------------------------------------------- results as plain data


def presence_map(run: RunResult) -> PresenceMap:
    unavailable = (m for m, st in run.status.items() if st in (STATUS_FAILED, STATUS_MISSING))
    return PresenceMap(run.present, unavailable)


def trace_records(trace: Trace | None) -> tuple[TraceRecord, ...]:
    if trace is None:
        return ()
    decisions: dict[int, list] = {}
    for d in trace.decisions:
        decisions.setdefault(d.ref, []).append(d)
    out = []
    for r in trace.records:
        failed = frozenset(
            "trait" if d.stage in _TRAIT_STAGES else d.stage for d in decisions.get(r.rid, ()) if not d.verdict
        )
        out.append(TraceRecord(r.med, r.code, r.key, not failed, failed))
    return tuple(out)


# ---------------------------------------------------------------------- the broker


class BrokerEnv:
    """`Env` of one (contrast, view, capability, budget) cell. `prep_evidence` must hold the stored response of
    the full preparation set of D (and of any other available prep subset), as `Hybrids` expects."""

    def __init__(
        self,
        side: BrokerSide,
        contrast: Contrast,
        evidence: Evidence,
        hier: Hierarchy,
        view_dir: Path,
        capability: str,
        budget: int | None,
        *,
        prep_evidence: Mapping[tuple[str, ...], Evidence] | None = None,
    ) -> None:
        self.side = side
        self._contrast = contrast
        self.view_dir = Path(view_dir)
        self._capability = capability
        self.cell = cell = CellSpec.of(side.view, capability)  # L1 x R-A/R-B: ValueError (SPEC 7.3)
        self._manifest = read_manifest(self.view_dir)
        self._entries = {e.ref: e for e in self._manifest.entries}
        self._truth = Hybrids(contrast, evidence, hier, levels="executed", prep_evidence=prep_evidence)
        self.dropped_edits: tuple[tuple[str, int], ...] = ()
        if cell.full_response and cell.code_link:
            self.replay = self._truth
        else:
            r_contrast, r_evidence, r_prep = contrast, evidence, prep_evidence
            if not cell.full_response:
                filtered = [_filter_patch(p) for p in contrast.patches]
                r_contrast = replace(contrast, patches=tuple(p for p, _ in filtered))
                self.dropped_edits = tuple((p.id, n) for p, n in filtered if n)
                r_evidence = top1_evidence(evidence)
                r_prep = {k: top1_evidence(v) for k, v in (prep_evidence or {}).items()}
            levels = "executed" if cell.code_link else "declared"
            self.replay = Hybrids(r_contrast, r_evidence, hier, levels=levels, prep_evidence=r_prep)

        members = set(self.replay.D)
        if cell.code_link:
            members |= set(Hybrids(contrast, evidence, hier, levels="declared").D)
        patch_handle_of = {member: handle for handle, member in side.handles}
        self._h2m: dict[str, str] = {}
        for m in sorted(members):
            if m.startswith("patch:"):
                if not cell.evidence:
                    continue  # SPEC 11.1: opaque patch handles only when the responses are visible
                if m not in patch_handle_of:
                    raise ValueError(f"no opaque handle for {m} in the broker side of view {side.vid}")
                self._h2m[patch_handle_of[m]] = m
            else:
                self._h2m[m] = m
        prep = set(contrast.prep_factors)
        self.ledger = Ledger(
            frozenset(self._h2m),
            capability,
            budget,
            inert=frozenset(h for h, m in self._h2m.items() if self._is_inert(m)),
            rb_refused=frozenset(h for h, m in self._h2m.items() if m in prep),
        )
        self._budget = budget
        self._bytes = 0
        self._cpu = 0.0
        self._finals: dict[str, PresenceMap] = {}

    # ------------------------------------------------------------------ helpers

    def _is_inert(self, member: str) -> bool:
        """SPEC 7.4: the replay realizes the same run with and without the handle."""
        h = self.replay
        if member not in h.D:
            return True
        return h.prep_key((member,)) == () and h.config((member,)) == h.config(())

    def _members(self, handles: Iterable[str]) -> frozenset[str]:
        return frozenset(self._h2m[h] for h in handles)

    def _admissible(self, k: frozenset[str]) -> bool:
        S = self._members(k)
        if not default_expressible(self.cell, self.replay, S):
            raise Unavailable(NOT_EXPRESSIBLE, ",".join(sorted(k)))
        return self.replay.admissible(S)

    def _run(self, k: frozenset[str]) -> EvalResult:
        t0 = time.process_time()
        try:
            res = self.replay.run(self._members(k), trace=True)
        finally:
            self._cpu += time.process_time() - t0
        return EvalResult(presence_map(res), trace_records(res.trace))

    @staticmethod
    def _check_run(run: str) -> None:
        if run not in RUNS:
            raise ValueError(f"unknown run {run!r}")

    # ------------------------------------------------------------------ Env

    def contrast(self) -> ContrastInfo:
        space = SYSTEM_ICD10_WHO if self._contrast.space == "who" else SYSTEM_ICD10CM
        return ContrastInfo(self.side.vid, RUNS, space, self._budget)

    def artifacts(self) -> Sequence[ArtifactRef]:
        return tuple(ArtifactRef(e.ref, e.kind, e.run) for e in self._manifest.entries)

    def read(self, ref: ArtifactRef) -> bytes:
        entry = self._entries.get(ref.ref)
        if entry is None:
            raise Unavailable(NOT_VISIBLE, ref.ref)
        data = (self.view_dir / entry.file).read_bytes()
        self._bytes += len(data)
        return data

    def config(self, run: str) -> Mapping[str, str]:
        self._check_run(run)
        return public_config((self._contrast.d0 if run == "x0" else self._contrast.d1).items)

    def executed_config(self, run: str) -> Mapping[str, str]:
        self._check_run(run)
        if not self.cell.code_link:
            raise Unavailable(NOT_VISIBLE, "code_link")
        return public_config((self._contrast.x0 if run == "x0" else self._contrast.x1).items)

    def final(self, run: str) -> Mapping[AssocKey, Presence]:
        """Observed finals: the executed truth runs on the full evidence, free (SPEC 7.4)."""
        self._check_run(run)
        if run not in self._finals:
            S = frozenset() if run == "x0" else frozenset(self._truth.D)
            self._finals[run] = presence_map(self._truth.run(S))
        return self._finals[run]

    def factors(self) -> Sequence[str]:
        return tuple(sorted(self._h2m))

    def capability(self) -> str:
        return self._capability

    def evaluate(self, apply: frozenset[str]) -> EvalResult:
        return self.ledger.evaluate(frozenset(apply), self._admissible, self._run)

    def meter(self) -> Meter:
        return Meter(evaluations=len(self.ledger.log), bytes_read=self._bytes, cpu_seconds=self._cpu, peak_rss=0)
