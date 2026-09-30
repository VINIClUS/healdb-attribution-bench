"""Output validation, backing and the total scoring table (SPEC §9).

Inputs use canonical factor names: the runner translates the `Env` handles (`ev:<hmac8>`) back to
`patch:<id>` before scoring (SPEC 9.2 step 0). Certificates and outputs are plain frozen dataclasses so
that any method-side schema can be adapted with `Output.of(...)`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from habench.oracle.families import subsets
from habench.oracle.truth import CellSpec, ContrastTruth, QueryTruth, split_view
from habench.types import Family, OutputState

S_ = OutputState
OUTCOMES = (
    "correto_sustentado", "errado", "indevidamente_exclusivo", "nao_comprometido",
    "abstencao_apropriada", "abstencao_desnecessaria", "falha", "excluido",
)
CERT_KINDS = ("final", "eval", "trace", "dummy")


@dataclass(frozen=True)
class Certificate:
    kind: str
    subject: frozenset[str]  # S, or {f} for dummy
    value: bool


@dataclass(frozen=True)
class Output:
    state: OutputState
    families: tuple[Family, ...] = ()
    certificates: tuple[Certificate, ...] = ()
    reason: str = ""

    @classmethod
    def of(cls, state: str, families: Iterable[Iterable[Iterable[str]]] = (),
           certificates: Iterable[tuple[str, Iterable[str], bool]] = (), reason: str = "") -> Output:
        return cls(
            OutputState(state),
            tuple(frozenset(frozenset(S) for S in F) for F in families),
            tuple(Certificate(k, frozenset(s), bool(v)) for k, s, v in certificates),
            reason,
        )


# ---------------------------------------------------------------------- 9.1 validation


def _valid_family(F: Family) -> bool:
    return bool(F) and all(S for S in F) and not any(a < b for a in F for b in F)


def validate(out: Output) -> Output:
    """SPEC 9.1: an invalid output becomes `falha_de_execucao` with reason `invalid_output`."""
    fams = out.families
    ok = True
    if out.state == S_.EXPLICACAO_VERIFICADA:
        ok = len(fams) == 1 and _valid_family(fams[0])
    elif out.state == S_.ALTERNATIVAS:
        ok = len(set(fams)) >= 2 and len(set(fams)) == len(fams) and all(_valid_family(F) for F in fams)
    elif fams:
        ok = False
    return out if ok else Output(S_.FALHA_DE_EXECUCAO, (), (), "invalid_output")


# ---------------------------------------------------------------------- 9.2 backing


@dataclass(frozen=True)
class Backing:
    all_true: bool
    covered: bool
    discarded: tuple[tuple[Certificate, str], ...] = field(default=())


def accepted(cert: Certificate, D: frozenset[str], cell: CellSpec, log: frozenset[frozenset[str]]) -> str:
    """"" if the certificate is accepted in this execution (SPEC 9.2 table), else the discard reason."""
    if cert.kind not in CERT_KINDS:
        return "unknown_kind"
    S = cert.subject & D
    ends = S in (frozenset(), D)
    in_log = cell.runs_hybrids and S in log
    if cert.kind == "final":
        return "" if ends else "final_not_endpoint"
    if cert.kind == "eval":
        return "" if in_log else "eval_not_in_log"
    if cert.kind == "trace":
        stored = split_view(cell.view)[0] in ("L2-M", "L3-M") and ends
        return "" if stored or in_log else "trace_unavailable"
    if len(S) != 1:
        return "dummy_not_single_factor"
    return "" if cell.evidence else "dummy_without_evidence"


def backing(
    q: QueryTruth,
    D: Iterable[str],
    certificates: Sequence[Certificate],
    cell: CellSpec,
    log: Iterable[Iterable[str]],
) -> Backing:
    D = frozenset(D)
    logged = frozenset(frozenset(S) & D for S in log)
    all_true = True
    discarded: list[tuple[Certificate, str]] = []
    certified: dict[frozenset[str], bool] = {}
    Z: set[str] = set()
    for cert in certificates:
        why = accepted(cert, D, cell, logged)
        if why:
            discarded.append((cert, why))
            continue
        S = cert.subject & D
        if cert.kind == "dummy":
            (f,) = S
            all_true &= q.is_dummy(f) == cert.value
            if cert.value:
                Z.add(f)
            continue
        truth = q.sufficient(S)
        all_true &= truth is not None and truth == cert.value
        certified[S] = cert.value
    classes = {S - Z for S in certified}
    suff_classes = [S - Z for S, v in certified.items() if v]
    covered = all((S - Z) in classes or any(T < S - Z for T in suff_classes) for S in subsets(D))
    return Backing(all_true, covered, tuple(discarded))


# ---------------------------------------------------------------------- 9.3 scoring


def score_cell(
    cell: str,
    out: Output,
    *,
    backing_: Backing | None,
    F_star: Family | None,
    W_lo: frozenset[Family] | None,
    W_hi: frozenset[Family] | None,
    F_adm: Family | None,
    necessity: int,
    budget: int,
) -> str:
    """SPEC 9.3, total over (cell, state). Precedence: errado > indevidamente exclusivo > nao comprometido >
    correto sustentado. `out` must already be validated."""
    st = out.state
    if st == S_.FALHA_DE_EXECUCAO:
        return "falha"
    if cell == "indeterminado":
        return "excluido"
    changed = cell in ("identificado", "ambiguo", "incompleta")
    if st == S_.EXPLICACAO_VERIFICADA:
        (F,) = out.families
        if backing_ is not None and not backing_.all_true:
            return "errado"
        if cell == "identificado":
            if F != F_star:
                return "errado"
            return "correto_sustentado" if backing_ is not None and backing_.covered else "indevidamente_exclusivo"
        if cell == "ambiguo":
            return "indevidamente_exclusivo" if F == F_star else "errado"
        if cell == "incompleta":
            return "indevidamente_exclusivo" if F == F_adm else "errado"
        return "errado"
    if st == S_.ALTERNATIVAS:
        A = frozenset(out.families)
        if cell == "identificado":
            return "nao_comprometido" if F_star in A else "errado"
        if cell == "ambiguo":
            if F_star not in A:
                return "errado"
            if not W_lo <= A:
                return "indevidamente_exclusivo"
            return "correto_sustentado" if A <= W_hi else "nao_comprometido"
        if cell == "incompleta":
            return "nao_comprometido" if F_adm in A else "errado"
        return "errado"
    if st == S_.AUSENCIA_DE_MUDANCA:
        return "errado" if changed else "correto_sustentado"
    if st == S_.COMPATIVEL_COM_VARIABILIDADE:
        return "errado" if changed else "nao_comprometido"
    if cell == "inalterado":
        return "abstencao_desnecessaria"
    if st == S_.INFORMACAO_INSUFICIENTE:
        return "abstencao_apropriada" if cell in ("ambiguo", "incompleta") else "abstencao_desnecessaria"
    if st == S_.CONTRAFACTUAL_INDISPONIVEL:
        return "abstencao_apropriada" if cell == "incompleta" else "abstencao_desnecessaria"
    if st == S_.ORCAMENTO_ESGOTADO:
        return "abstencao_apropriada" if necessity > budget else "abstencao_desnecessaria"
    raise ValueError(f"unknown state {st!r}")


@dataclass(frozen=True)
class Scored:
    qid: str
    cell: str
    state: OutputState
    outcome: str
    backing: Backing | None
    reason: str


def score_query(
    truth: ContrastTruth,
    qid: str,
    raw: Output,
    cell: CellSpec,
    *,
    budget: int,
    log: Iterable[Iterable[str]] = (),
) -> Scored:
    """Validate, back and score one output of one execution (method × view × capability × budget)."""
    q = truth.query(qid)
    out = validate(raw)
    c = q.cell(cell.view, cell.capability)
    ident = q.ident.get((cell.view, cell.capability))
    b = None
    if out.state == S_.EXPLICACAO_VERIFICADA and c != "indeterminado":
        b = backing(q, truth.contrast.D, out.certificates, cell, log)
    outcome = score_cell(
        c, out, backing_=b, F_star=q.F_star, W_lo=ident.W_lo if ident else None,
        W_hi=ident.W_hi if ident else None, F_adm=q.F_adm,
        necessity=truth.necessity[(cell.view, cell.capability)], budget=budget,
    )
    return Scored(qid, c, out.state, outcome, b, out.reason)
