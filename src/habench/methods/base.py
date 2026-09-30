"""Method-side contract (SPEC §11.1): the `Env` seen by methods, the output schema and its validation.

This module is imported inside the isolated method process. It must stay free of `habench.pipeline`,
`habench.oracle` and `habench.scenarios` (SPEC §11.2): the broker imports from here, never the reverse.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal, Protocol

from habench.types import CATEGORICAL, AssocKey, OutputState, Presence

CAPABILITIES = ("R-A", "R-B", "R-C")

# Reasons carried by `Unavailable`. BFS completeness (§6.3 step 4) counts only INADMISSIBLE skips.
INADMISSIBLE = "inadmissible"
NO_REPLAY = "no_replay"  # capability refuses: R-C, or R-B with a prep/acm factor
NOT_EXPRESSIBLE = "not_expressible"  # N1/N2: S not expressible in the historical code (§7.1)
NOT_VISIBLE = "not_visible"  # artifact or executed config absent from the view

# Standard abstention reasons (§11.1).
OUTPUT_DIFF_ONLY = "output_diff_only"
REPLAY_INVALIDO = "replay_invalido"
EVIDENCIA_OCULTA = "evidencia_oculta"
AMBIGUIDADE = "ambiguidade"
SEM_RESPOSTA_ARMAZENADA = "sem_resposta_armazenada"
ORCAMENTO = "orcamento"
INVALID_OUTPUT = "invalid_output"


class Unavailable(RuntimeError):
    """The Env cannot serve the request. Costs nothing (§7.4)."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


class BudgetExhausted(RuntimeError):
    """A new distinct evaluation would exceed the per-contrast budget."""


@dataclass(frozen=True, slots=True)
class ContrastInfo:
    cid: str  # opaque contrast id
    runs: tuple[str, str]  # ("x0", "x1")
    space: str  # comparison space: habench.types.SYSTEM_ICD10_WHO or SYSTEM_ICD10CM
    budget: int | None  # evaluations per contrast (§7.4); None = unlimited


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    ref: str  # opaque id
    kind: str  # SPEC table 7.1 kind, e.g. "acm_response", "trace", "trace_winners"
    run: str  # "x0" | "x1" | "" for run-independent artifacts


@dataclass(frozen=True, slots=True)
class TraceRecord:
    """One record of a hybrid's decision trace, as plain data (no pipeline types cross the boundary)."""

    med: int
    code: str
    key: AssocKey | None  # None: unmapped
    verdict: bool  # True = approved
    failed: frozenset[str]  # subset of {trait, ent_thr, icd_thr, map}


class PresenceMap(Mapping[AssocKey, Presence]):
    """Presence of a whole run (§1.4): iterates the PRESENT keys; every key of an unavailable med is UNAVAILABLE;
    any other key is missing, i.e. ABSENT through `presence()`."""

    __slots__ = ("present", "unavailable")

    def __init__(self, present: Iterable[AssocKey] = (), unavailable: Iterable[int] = ()) -> None:
        self.present = frozenset(present)
        self.unavailable = frozenset(unavailable)

    def __getitem__(self, key: AssocKey) -> Presence:
        if key.med in self.unavailable:
            return Presence.UNAVAILABLE
        if key in self.present:
            return Presence.PRESENT
        raise KeyError(key)

    def __iter__(self):
        return iter(sorted(self.present))

    def __len__(self) -> int:
        return len(self.present)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PresenceMap):
            return self.present == other.present and self.unavailable == other.unavailable
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.present, self.unavailable))

    def __repr__(self) -> str:
        return f"PresenceMap({len(self.present)} present, unavailable meds {sorted(self.unavailable)})"

    def to_json(self) -> dict:
        return {
            "present": [[k.med, k.system, k.version, k.code] for k in sorted(self.present)],
            "unavailable": sorted(self.unavailable),
        }

    @classmethod
    def from_json(cls, obj: Mapping) -> PresenceMap:
        return cls((AssocKey(*k) for k in obj["present"]), obj["unavailable"])


@dataclass(frozen=True, slots=True)
class EvalResult:
    presence: Mapping[AssocKey, Presence]  # whole group, in the contrast space
    trace: tuple[TraceRecord, ...]

    def state(self, key: AssocKey) -> Presence:
        return presence(self.presence, key)


@dataclass(frozen=True, slots=True)
class Meter:
    """Raw cost of one contrast; `amortized` divides it by the contrast's queries (§10.3). Peak RSS is not divided."""

    evaluations: float = 0  # distinct evaluated sets
    bytes_read: float = 0
    cpu_seconds: float = 0.0
    peak_rss: int = 0  # bytes

    def amortized(self, n_queries: int) -> Meter:
        n = max(n_queries, 1)
        return Meter(self.evaluations / n, self.bytes_read / n, self.cpu_seconds / n, self.peak_rss)


@dataclass(frozen=True, slots=True, order=True)
class Query:
    qid: str
    key: AssocKey


@dataclass(frozen=True, slots=True)
class Certificate:
    kind: Literal["final", "eval", "trace", "dummy"]
    subject: tuple[str, ...]  # S (handles) or (factor,)
    value: bool  # sufficient? / dummy?


FamilyT = tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class Explanation:
    qid: str
    state: OutputState
    families: tuple[FamilyT, ...] = ()
    certificates: tuple[Certificate, ...] = ()
    reason: str = ""
    confidence: float | None = None
    # Free-form notes (e.g. "incomplete partial family"); never scored.
    notes: tuple[str, ...] = field(default=())


class Env(Protocol):
    def contrast(self) -> ContrastInfo: ...
    def artifacts(self) -> Sequence[ArtifactRef]: ...
    def read(self, ref: ArtifactRef) -> bytes: ...
    def config(self, run: str) -> Mapping[str, str]: ...
    def executed_config(self, run: str) -> Mapping[str, str]: ...
    def final(self, run: str) -> Mapping[AssocKey, Presence]: ...
    def factors(self) -> Sequence[str]: ...
    def capability(self) -> str: ...
    def evaluate(self, apply: frozenset[str]) -> EvalResult: ...
    def meter(self) -> Meter: ...


class Method(Protocol):
    name: str

    def explain(self, env: Env, queries: Sequence[Query]) -> Mapping[str, Explanation]: ...


def presence(m: Mapping[AssocKey, Presence], key: AssocKey) -> Presence:
    """Presence maps list PRESENT and UNAVAILABLE keys; a key missing from the map is ABSENT (§1.4)."""
    return m.get(key, Presence.ABSENT)


def same_presence(a: Mapping[AssocKey, Presence], b: Mapping[AssocKey, Presence]) -> bool:
    """Decision-level equality (§2, level 3), ignoring explicit ABSENT entries."""

    if isinstance(a, PresenceMap) and isinstance(b, PresenceMap):
        return a == b

    def norm(m: Mapping[AssocKey, Presence]) -> dict[AssocKey, Presence]:
        return {k: v for k, v in m.items() if v != Presence.ABSENT}

    return norm(a) == norm(b)


def changed(env: Env, key: AssocKey) -> bool:
    """Whether the observed finals differ for `key` (reading finals is free, §7.4)."""
    return presence(env.final("x0"), key) != presence(env.final("x1"), key)


def final_certificates(D: Iterable[str]) -> tuple[Certificate, ...]:
    """The two free certificates of §9.2: suff(∅) is false and suff(D) is true for a changed query."""
    return (Certificate("final", (), False), Certificate("final", canonical_set(D), True))


def canonical_set(s: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(s)))


def canonical_family(sets: Iterable[Iterable[str]]) -> FamilyT:
    """Sorted by (size, names): the BFS discovery order of §6.3."""
    return tuple(sorted({canonical_set(s) for s in sets}, key=lambda t: (len(t), t)))


def is_antichain(family: FamilyT) -> bool:
    sets = [frozenset(s) for s in family]
    return all(not (a < b) for a in sets for b in sets)


def output_error(e: Explanation) -> str | None:
    """Why `e` violates the schema of §9.1 (EX-23), or None."""
    fams = e.families
    for fam in fams:
        if not fam or any(not s for s in fam):
            return "empty family or empty set"
        if len({canonical_set(s) for s in fam}) != len(fam) or not is_antichain(fam):
            return "family is not an antichain"
    distinct = {frozenset(frozenset(s) for s in fam) for fam in fams}
    if e.state == OutputState.EXPLICACAO_VERIFICADA:
        return None if len(fams) == 1 else "explicacao_verificada needs exactly one family"
    if e.state == OutputState.ALTERNATIVAS:
        return None if len(distinct) >= 2 and len(distinct) == len(fams) else "alternativas needs >= 2 distinct families"
    if e.state not in CATEGORICAL or e.state in (OutputState.AUSENCIA_DE_MUDANCA, OutputState.COMPATIVEL_COM_VARIABILIDADE):
        return "families on a state without families" if fams else None
    return None


def validated(e: Explanation) -> Explanation:
    """Invalid output becomes `falha_de_execucao` with reason `invalid_output` (§9.1)."""
    err = output_error(e)
    if err is None:
        return e
    return replace(e, state=OutputState.FALHA_DE_EXECUCAO, families=(), reason=INVALID_OUTPUT, notes=e.notes + (err,))


def abstain(qid: str, state: OutputState, reason: str, *notes: str) -> Explanation:
    return Explanation(qid=qid, state=state, reason=reason, notes=notes)
