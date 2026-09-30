"""Minimal families of one association from its truth table (SPEC 6.1-6.3).

The truth table maps every *admissible* S ⊆ D to state_S(a); inadmissible subsets are absent.
- `analyze` runs the O(|D|·2^|D|) recurrences of SPEC 6.2 and returns the family relative to the
  admissible subsets (`F*_adm`), completeness (6.1) and the non-monotone flag.
- `naive_family` is the O(3^n) reference used by the property tests.
- `reference_bfs` is the joint method-side search of SPEC 6.3 that defines the budget necessity.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

from habench.types import Family

Table = Mapping[frozenset[str], Hashable]


def subsets(D: Iterable[str]) -> list[frozenset[str]]:
    names = sorted(D)
    return [frozenset(s) for k in range(len(names) + 1) for s in combinations(names, k)]


@dataclass(frozen=True)
class FamilyResult:
    changed: bool
    family: Family | None  # F*_adm; equals F* when complete; None when unchanged
    complete: bool | None
    nonmonotone: bool | None
    sufficient: frozenset[frozenset[str]]


def analyze(D: Iterable[str], table: Table) -> FamilyResult:
    D = frozenset(D)
    empty = frozenset()
    if empty not in table or D not in table:
        raise ValueError("the endpoints ∅ and D must be admissible")
    if table[empty] == table[D]:
        return FamilyResult(False, None, None, None, frozenset())
    target = table[D]
    subs = subsets(D)
    suff = {S for S in subs if S in table and table[S] == target}
    sub: dict[frozenset[str], bool] = {}
    minimal: set[frozenset[str]] = set()
    for S in subs:  # by size, so every S - {i} is already known
        below = any(sub[S - {i}] for i in S)
        sub[S] = S in suff or below
        if S in suff and not below:
            minimal.add(S)
    complete = all(any(T < S for T in suff) for S in subs if S not in table)
    nonmono = any(T > S and T in table and T not in suff for S in suff for T in subs)
    return FamilyResult(True, frozenset(minimal), complete, nonmono, frozenset(suff))


def naive_family(D: Iterable[str], table: Table) -> Family | None:
    """O(3^n): S is minimal iff sufficient and no admissible proper subset is sufficient."""
    D = frozenset(D)
    if table[frozenset()] == table[D]:
        return None
    target = table[D]
    suff = [S for S in subsets(D) if S in table and table[S] == target]
    return frozenset(S for S in suff if not any(T < S for T in suff))


# ---------------------------------------------------------------------- SPEC 6.3 reference BFS


@dataclass(frozen=True)
class BFSResult:
    evaluated: tuple[frozenset[str], ...]
    families: dict[Hashable, Family]  # per query (only for changed queries)
    complete: dict[Hashable, bool]
    exhausted: bool


def reference_bfs(
    D: Sequence[str],
    queries: Mapping[Hashable, Callable[[frozenset[str]], Hashable]],
    *,
    budget: int | None = None,
    admissible: Callable[[frozenset[str]], bool] = lambda S: True,
    dummies: Mapping[Hashable, frozenset[str]] | None = None,
) -> BFSResult:
    """Joint BFS over the queries of one contrast (SPEC 6.3).

    `queries[q](S)` is state_S(q), evaluated through a shared cache (one evaluation per distinct S).
    A subset is skipped only if it is pruned for every query still open. Queries whose endpoints are
    equal are unchanged and never open.
    """
    names = sorted(D)
    full = frozenset(names)
    dummies = dummies or {}
    evaluated: list[frozenset[str]] = []
    cache: dict[frozenset[str], None] = {}
    exhausted = False

    def spend(S: frozenset[str]) -> bool:
        if S in cache:
            return True
        if budget is not None and len(evaluated) >= budget:
            return False
        evaluated.append(S)
        cache[S] = None
        return True

    spend(frozenset())
    ok = spend(full)
    found: dict[Hashable, list[frozenset[str]]] = {}
    skipped: dict[Hashable, list[frozenset[str]]] = {}
    targets: dict[Hashable, Hashable] = {}
    if ok:
        for q, st in queries.items():
            if st(frozenset()) != st(full):
                targets[q] = st(full)
                found[q], skipped[q] = [], []
    else:
        exhausted = True
    for k in range(1, len(names)):
        if exhausted:
            break
        for combo in combinations(names, k):
            S = frozenset(combo)
            open_q = [q for q in targets if not any(T <= S for T in found[q]) and not (S & dummies.get(q, frozenset()))]
            if not open_q:
                continue
            if not admissible(S):
                for q in open_q:
                    skipped[q].append(S)
                continue
            if not spend(S):
                exhausted = True
                break
            for q in open_q:
                if queries[q](S) == targets[q]:
                    found[q].append(S)
    families: dict[Hashable, Family] = {}
    complete: dict[Hashable, bool] = {}
    for q in targets:
        fam = set(found[q])
        if not exhausted and not fam:
            fam.add(full)
        families[q] = frozenset(fam)
        complete[q] = not exhausted and all(any(T < S for T in found[q]) for S in skipped[q])
    return BFSResult(tuple(evaluated), families, complete, exhausted)


def necessity(
    D: Sequence[str],
    queries: Mapping[Hashable, Callable[[frozenset[str]], Hashable]],
    *,
    admissible: Callable[[frozenset[str]], bool] = lambda S: True,
    dummies: Mapping[Hashable, frozenset[str]] | None = None,
) -> int:
    """Evaluations of the unbudgeted joint reference BFS (SPEC 9.3 "necessidade")."""
    return len(reference_bfs(D, queries, admissible=admissible, dummies=dummies).evaluated)
