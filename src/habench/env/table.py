"""In-process `Env` over explicit truth tables: the test double for methods and search.

It applies the same budget, cache and refusal rules as the broker (SPEC §7.3, §7.4) through `Ledger`, so the
contract tests in `tests/test_env_contract.py` run against both.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from habench.methods.base import (
    CAPABILITIES,
    INADMISSIBLE,
    NO_REPLAY,
    NOT_VISIBLE,
    ArtifactRef,
    BudgetExhausted,
    ContrastInfo,
    EvalResult,
    Meter,
    Unavailable,
)
from habench.types import SYSTEM_ICD10_WHO, AssocKey, Presence

Replay = Callable[[frozenset[str]], EvalResult]


@dataclass
class Ledger:
    """Budget and cache bookkeeping shared by every Env implementation (§7.4).

    Order of checks: unknown handle -> ValueError; R-C -> Unavailable; strip inert handles; cache hit -> free;
    refused or inadmissible -> Unavailable; over budget -> BudgetExhausted; else run and charge one unit.
    """

    handles: frozenset[str]
    capability: str
    budget: int | None
    inert: frozenset[str] = frozenset()  # handles whose level, as the broker uses it, is equal in x0 and x1
    rb_refused: frozenset[str] = frozenset()  # prep/acm (non-patch) handles that R-B cannot run
    cache: dict[frozenset[str], EvalResult] = field(default_factory=dict)
    log: list[frozenset[str]] = field(default_factory=list)  # distinct evaluated sets, in order

    def __post_init__(self) -> None:
        if self.capability not in CAPABILITIES:
            raise ValueError(f"unknown capability {self.capability!r}")

    def key(self, apply: frozenset[str]) -> frozenset[str]:
        unknown = apply - self.handles
        if unknown:
            raise ValueError(f"unknown handles {sorted(unknown)}")
        if self.capability == "R-C":
            raise Unavailable(NO_REPLAY, "R-C")
        return frozenset(apply) - self.inert

    def evaluate(
        self, apply: frozenset[str], admissible: Callable[[frozenset[str]], bool], run: Replay
    ) -> EvalResult:
        k = self.key(frozenset(apply))
        if k in self.cache:
            return self.cache[k]
        if self.capability == "R-B" and k & self.rb_refused:
            raise Unavailable(NO_REPLAY, "R-B cannot run prep/acm factors")
        if not admissible(k):
            raise Unavailable(INADMISSIBLE, ",".join(sorted(k)))
        if self.budget is not None and len(self.log) >= self.budget:
            raise BudgetExhausted(f"budget {self.budget} spent")
        result = run(k)
        self.cache[k] = result
        self.log.append(k)
        return result


@dataclass
class TableEnv:
    """An Env whose hybrids come from a function of the applied handle set (after inert handles are removed)."""

    handles: Sequence[str]
    replay: Replay
    capability_: str = "R-A"
    budget: int | None = None
    inadmissible: frozenset[frozenset[str]] = frozenset()
    inert: frozenset[str] = frozenset()
    rb_refused: frozenset[str] = frozenset()
    space: str = SYSTEM_ICD10_WHO
    configs: Mapping[str, Mapping[str, str]] = field(default_factory=lambda: {"x0": {}, "x1": {}})
    executed: Mapping[str, Mapping[str, str]] | None = None  # None: no code_link in the view
    finals: Mapping[str, Mapping[AssocKey, Presence]] | None = None  # default: replay of ∅ and D, uncharged
    blobs: Mapping[ArtifactRef, bytes] = field(default_factory=dict)
    cid: str = "c0"

    def __post_init__(self) -> None:
        self.ledger = Ledger(
            frozenset(self.handles), self.capability_, self.budget, frozenset(self.inert), frozenset(self.rb_refused)
        )
        self._bytes = 0
        if self.finals is None:
            everything = frozenset(self.handles) - frozenset(self.inert)
            self.finals = {"x0": dict(self.replay(frozenset()).presence), "x1": dict(self.replay(everything).presence)}

    def contrast(self) -> ContrastInfo:
        return ContrastInfo(self.cid, ("x0", "x1"), self.space, self.budget)

    def artifacts(self) -> Sequence[ArtifactRef]:
        return tuple(self.blobs)

    def read(self, ref: ArtifactRef) -> bytes:
        if ref not in self.blobs:
            raise Unavailable(NOT_VISIBLE, ref.ref)
        data = self.blobs[ref]
        self._bytes += len(data)
        return data

    def config(self, run: str) -> Mapping[str, str]:
        return dict(self.configs[run])

    def executed_config(self, run: str) -> Mapping[str, str]:
        if self.executed is None:
            raise Unavailable(NOT_VISIBLE, "code_link")
        return dict(self.executed[run])

    def final(self, run: str) -> Mapping[AssocKey, Presence]:
        assert self.finals is not None
        return dict(self.finals[run])

    def factors(self) -> Sequence[str]:
        return tuple(self.handles)

    def capability(self) -> str:
        return self.capability_

    def evaluate(self, apply: frozenset[str]) -> EvalResult:
        return self.ledger.evaluate(frozenset(apply), lambda s: s not in self.inadmissible, self.replay)

    def meter(self) -> Meter:
        return Meter(evaluations=len(self.ledger.log), bytes_read=self._bytes)

    @property
    def log(self) -> list[frozenset[str]]:
        return self.ledger.log


def single_key_replay(key: AssocKey, sufficient: Iterable[Iterable[str]], x0: Presence, x1: Presence) -> Replay:
    """Replay for one association: `x1` state exactly on the listed sets, `x0` state elsewhere."""
    suff = {frozenset(s) for s in sufficient}

    def run(s: frozenset[str]) -> EvalResult:
        return EvalResult({key: x1 if s in suff else x0}, ())

    return run
