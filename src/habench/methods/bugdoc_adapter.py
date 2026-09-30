"""BugDoc comparator (Stacked Shortcut, standalone mode) behind the `Method` contract (SPEC §11.1).

Vendored upstream code lives in `third_party/bugdoc` (read-only, commit in its NOTICE.md) and is imported by
putting that directory on `sys.path`. Method-side module: no import of `habench.pipeline`, `habench.oracle`
or `habench.scenarios`.

Semantic difference. BugDoc asserts a *definitive root cause*: a conjunction such that every instance of the
whole parameter universe satisfying it fails. The SPEC asks for minimal sufficient sets in the x0 context
(§6.1): S is sufficient when the hybrid that applies S on top of x0 reproduces the x1 state of the query. The
adapter maps the parameter space to {factor: ["x0", "x1"]}; a BugDoc "failure" is "the hybrid reproduces the
x1 state". In a conjunction only the x1-valued literals become members of S. The x0-valued literals carry
BugDoc's "definitive over all contexts" meaning (the factor must stay at x0 whatever the others do); the SPEC
only claims sufficiency in the x0 context, so they are dropped (with the two-row history used here they
never occur). Conjunctions that reduce to the empty set are dropped and the minimal antichain of the rest is
emitted as ONE family (`explicacao_verificada`). Nothing is checked beyond what BugDoc evaluated: its answer
need not be the complete family of minimal sufficient sets, and a set it asserts may be non-minimal
(truncated shortcuts are not the failure mode; over-long ones can be, see below).

Code-vs-paper differences that affect this adapter (docs/design/ambiente_e_comparadores.md §2):
- Standalone Stacked Shortcut never resets `cf` to CPf between good instances. With the two-row history
  seeded here there is a single good instance (all x0), so it does not matter; it matters for the fidelity
  tests with k > 1 (see tests/test_methods_bugdoc.py).
- `cf_aux not in self.expers` uses the history as it was at the start of `run`: a set evaluated twice inside a
  run is executed twice by BugDoc. The Env cache (§7.4) makes the repeat free, and the meter counts distinct
  sets only.
- Standalone mode appends every execution twice to its internal lists (no effect on results); `max_iter` only
  bounds the bootstrap stage, which never runs because the history is supplied. The real cutoff is the Env
  meter: `BudgetExhausted` aborts the whole BugDoc run (`orcamento_esgotado`, reason `orcamento`).
- Without a disjoint pair it picks a random pair (here the pair always exists: all-x0 / all-x1). Python
  `random` is seeded per query and the previous global state restored; numpy is not used on this path.
- An `Unavailable` evaluation returns None to BugDoc ("could not run"): it stops the shortcut loop for that
  good instance and is never treated as a success or a failure.
"""

from __future__ import annotations

import logging
import random
import sys
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from habench.methods.base import (
    AMBIGUIDADE,
    EVIDENCIA_OCULTA,
    ORCAMENTO,
    OUTPUT_DIFF_ONLY,
    BudgetExhausted,
    Certificate,
    Env,
    Explanation,
    Query,
    Unavailable,
    abstain,
    canonical_family,
    canonical_set,
    validated,
)
from habench.types import AssocKey, OutputState, Presence

_BUGDOC_ROOT = Path(__file__).resolve().parents[3] / "third_party" / "bugdoc"
if str(_BUGDOC_ROOT) not in sys.path:
    sys.path.insert(0, str(_BUGDOC_ROOT))

from bugdoc.algos.stacked_shortcut_standalone import StackedShortcutStandalone  # noqa: E402

X0, X1 = "x0", "x1"
_UNBOUNDED = 10**9


class _Abort(Exception):
    """Raised through BugDoc when the Env budget is spent."""


@dataclass(frozen=True)
class BugDocRun:
    causes: tuple[frozenset[str], ...]  # minimal antichain of x1-literal sets (possibly empty)
    evaluated: tuple[tuple[frozenset[str], bool], ...]  # (S, sufficient?) in call order, distinct
    exhausted: bool


@dataclass
class _Oracle:
    env: Env
    key: AssocKey
    x1_state: Presence
    factors: Sequence[str]
    seen: dict[frozenset[str], bool] = field(default_factory=dict)

    def __call__(self, params: Mapping[str, str]) -> bool | None:
        s = frozenset(f for f in self.factors if params[f] == X1)
        try:
            state = self.env.evaluate(s).state(self.key)
        except Unavailable:
            return None
        except BudgetExhausted:
            raise _Abort from None
        sufficient = state == self.x1_state
        self.seen.setdefault(s, sufficient)
        return not sufficient  # BugDoc: True = the pipeline succeeds, i.e. does NOT reproduce x1


def _minimal_antichain(sets: Sequence[frozenset[str]]) -> tuple[frozenset[str], ...]:
    uniq = set(sets)
    return tuple(s for s in sorted(uniq, key=lambda t: (len(t), sorted(t))) if not any(t < s for t in uniq))


def run_bugdoc(
    env: Env, key: AssocKey, x1_state: Presence, *, seed: int, k: int = 4, max_iter: int | None = None
) -> BugDocRun:
    """One Stacked Shortcut run for one association; history = the two free observed finals."""
    factors = tuple(env.factors())
    oracle = _Oracle(env, key, x1_state, factors)
    space = {f: [X0, X1] for f in factors}
    rows = [[X0] * len(factors) + [True], [X1] * len(factors) + [False]]
    history = [[list(r) for r in rows], [list(r) for r in rows]]
    algo = StackedShortcutStandalone(k=k, max_iter=max_iter or _UNBOUNDED, function=oracle)
    state = random.getstate()
    previous_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)  # upstream logs whole histories at DEBUG
    random.seed(seed)
    exhausted = False
    raw: list[list[tuple[int, str]]] = []
    try:
        raw = algo.run("bugdoc_in_memory", space, outputs=["result"], historical_runs=history)
    except _Abort:
        exhausted = True
    finally:
        logging.disable(previous_disable)
        random.setstate(state)
    sets = [frozenset(factors[i] for i, v in conj if v == X1) for conj in raw]
    sets = [s for s in sets if s]
    return BugDocRun(_minimal_antichain(sets), tuple(oracle.seen.items()), exhausted)


@dataclass(frozen=True)
class BugDocMethod:
    name: str = "bugdoc"
    k: int = 4

    def explain(self, env: Env, queries: Sequence[Query]) -> Mapping[str, Explanation]:
        out: dict[str, Explanation] = {}
        x0_final, x1_final = env.final(X0), env.final(X1)
        budget = env.contrast().budget
        full = frozenset(env.factors())
        for q in queries:
            s0, s1 = x0_final.get(q.key, Presence.ABSENT), x1_final.get(q.key, Presence.ABSENT)
            if Presence.UNAVAILABLE in (s0, s1):
                out[q.qid] = validated(abstain(q.qid, OutputState.INFORMACAO_INSUFICIENTE, EVIDENCIA_OCULTA))
            elif s0 == s1:
                out[q.qid] = validated(abstain(q.qid, OutputState.AUSENCIA_DE_MUDANCA, ""))
            elif env.capability() == "R-C":
                out[q.qid] = validated(abstain(q.qid, OutputState.INFORMACAO_INSUFICIENTE, OUTPUT_DIFF_ONLY))
            else:
                seed = zlib.crc32(f"{env.contrast().cid}|{q.qid}".encode())
                run = run_bugdoc(env, q.key, s1, seed=seed, k=self.k, max_iter=budget)
                out[q.qid] = validated(_explanation(q.qid, run, full))
        return out


def _explanation(qid: str, run: BugDocRun, full: frozenset[str]) -> Explanation:
    if run.exhausted:
        return abstain(qid, OutputState.ORCAMENTO_ESGOTADO, ORCAMENTO)
    if not run.causes:
        return abstain(qid, OutputState.INFORMACAO_INSUFICIENTE, AMBIGUIDADE, "bugdoc asserted no cause")
    certs = [Certificate("final", (), False), Certificate("final", canonical_set(full), True)]
    certs += [Certificate("eval", canonical_set(s), v) for s, v in run.evaluated]
    return Explanation(
        qid=qid,
        state=OutputState.EXPLICACAO_VERIFICADA,
        families=(canonical_family(run.causes),),
        certificates=tuple(certs),
    )
