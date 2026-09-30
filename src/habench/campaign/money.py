"""Paid-call authorization and the cumulative cost ledger.

Real calls need all of: env HAB_PAID_CALLS=1, the --paid flag, --budget-usd, and a price for every model used.
Before each attempt the worst case is reserved; the attempt is refused if spent + reserved would exceed the plan cap
(cumulative over the whole ledger) or the run budget. A reservation never reconciled (crash, interruption) stays
counted at its reserved value. Failed attempts are reconciled at worst case: whether they were billed is unknown.
"""

import fcntl
import json
import math
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from habench.campaign.plan import Plan
from habench.prov.records import utc_now

_EPS = 1e-9


class PaidCallRefused(RuntimeError):
    """A real call was requested without every authorization condition."""


class CapExceeded(RuntimeError):
    """Reserving the attempt's worst case would exceed the plan cap or the run budget."""


_AUTH_TOKEN = object()


@dataclass(frozen=True, slots=True)
class PaidAuthorization:
    """Proof that authorize_paid() accepted the request; only it can build one."""

    budget_usd: float
    cap_usd: float
    model_ids: frozenset[str]
    token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.token is not _AUTH_TOKEN:
            raise PaidCallRefused("PaidAuthorization can only be created by authorize_paid()")


def authorize_paid(*, paid_flag: bool, budget_usd: float | None, plan: Plan, model_ids: set[str],
                   env: Mapping[str, str] | None = None) -> PaidAuthorization:
    env = os.environ if env is None else env
    reasons = []
    if env.get("HAB_PAID_CALLS") != "1":
        reasons.append("env HAB_PAID_CALLS=1 not set")
    if not paid_flag:
        reasons.append("--paid not given")
    if budget_usd is None or not budget_usd > 0:
        reasons.append("--budget-usd <x> with x > 0 not given")
    missing = plan.missing_prices(model_ids)
    if missing:
        reasons.append(f"no price entry for model(s) {sorted(missing)}")
    if not plan.acm_price.usd_per_unit > 0:
        reasons.append("no ACM price")
    if reasons:
        raise PaidCallRefused("paid calls refused: " + "; ".join(reasons))
    assert budget_usd is not None
    return PaidAuthorization(budget_usd=budget_usd, cap_usd=plan.cap_usd, model_ids=frozenset(model_ids),
                             token=_AUTH_TOKEN)


@dataclass(frozen=True, slots=True)
class Totals:
    spent_usd: float  # reconciled values plus outstanding reservations
    outstanding_usd: float  # reserved, not yet reconciled
    run_spent_usd: dict[str, float]
    n_attempts: int


class Ledger:
    """Append-only JSONL ledger. path=None keeps entries in memory (dry runs, never written anywhere)."""

    def __init__(self, path: Path | None, entries: list[dict[str, Any]] | None = None) -> None:
        self.path = path
        self._mem: list[dict[str, Any]] = list(entries or [])
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    def dry_copy(self) -> "Ledger":
        """In-memory ledger preloaded with this ledger's entries; the file is only read."""
        return Ledger(None, self.entries())

    @contextmanager
    def _locked(self) -> Iterator[None]:
        if self.path is None:
            yield
            return
        with open(self.path, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def entries(self) -> list[dict[str, Any]]:
        if self.path is None:
            return list(self._mem)
        if not self.path.exists():
            return []
        out = []
        with open(self.path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if not line.endswith("\n"):
                    raise ValueError(f"{self.path}:{n}: truncated ledger line")
                out.append(json.loads(line))
        return out

    def _append(self, entry: dict[str, Any]) -> None:
        if self.path is None:
            self._mem.append(entry)
            return
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    @staticmethod
    def _totals(entries: list[dict[str, Any]]) -> Totals:
        reserved: dict[str, tuple[str, float]] = {}
        reconciled: dict[str, float] = {}
        for e in entries:
            if e["type"] == "reserve":
                reserved[e["attempt_id"]] = (e["run_id"], float(e["usd"]))
            elif e["type"] == "reconcile":
                reconciled[e["attempt_id"]] = float(e["usd"])
        per_run: dict[str, list[float]] = {}
        outstanding = []
        for aid, (run_id, usd) in reserved.items():
            value = reconciled.get(aid, usd)
            if aid not in reconciled:
                outstanding.append(usd)
            per_run.setdefault(run_id, []).append(value)
        run_spent = {r: math.fsum(v) for r, v in per_run.items()}
        return Totals(spent_usd=math.fsum(run_spent.values()), outstanding_usd=math.fsum(outstanding),
                      run_spent_usd=run_spent, n_attempts=len(reserved))

    def totals(self) -> Totals:
        return self._totals(self.entries())

    def reserve(self, *, attempt_id: str, run_id: str, usd: float, cap_usd: float, run_budget_usd: float,
                meta: Mapping[str, Any] | None = None) -> Totals:
        """Reserve the attempt's worst case, or raise CapExceeded without writing anything."""
        if not usd >= 0 or not math.isfinite(usd):
            raise ValueError(f"invalid reservation {usd!r}")
        with self._locked():
            entries = self.entries()
            if any(e["type"] == "reserve" and e["attempt_id"] == attempt_id for e in entries):
                raise ValueError(f"attempt {attempt_id} already reserved")
            t = self._totals(entries)
            run_spent = t.run_spent_usd.get(run_id, 0.0)
            if t.spent_usd + usd > cap_usd + _EPS:
                raise CapExceeded(f"cap: spent {t.spent_usd:.6f} + reserve {usd:.6f} > cap {cap_usd:.6f} USD")
            if run_spent + usd > run_budget_usd + _EPS:
                raise CapExceeded(
                    f"run budget: run spent {run_spent:.6f} + reserve {usd:.6f} > budget {run_budget_usd:.6f} USD")
            self._append({"type": "reserve", "attempt_id": attempt_id, "run_id": run_id, "usd": usd,
                          "ts": utc_now(), "meta": dict(meta or {})})
            return self._totals(self.entries())

    def reconcile(self, *, attempt_id: str, usd: float, basis: str) -> None:
        """Record the attempt's final cost. basis: measured | worst_case_failed | worst_case_orphan | ..."""
        if not usd >= 0 or not math.isfinite(usd):
            raise ValueError(f"invalid cost {usd!r}")
        with self._locked():
            entries = self.entries()
            res = [e for e in entries if e["type"] == "reserve" and e["attempt_id"] == attempt_id]
            if not res:
                raise ValueError(f"attempt {attempt_id} was never reserved")
            if any(e["type"] == "reconcile" and e["attempt_id"] == attempt_id for e in entries):
                raise ValueError(f"attempt {attempt_id} already reconciled")
            reserved = float(res[0]["usd"])
            self._append({"type": "reconcile", "attempt_id": attempt_id, "usd": usd, "basis": basis,
                          "ts": utc_now(), "exceeded_reservation": usd > reserved + _EPS})

    def outstanding(self, run_id: str | None = None) -> list[dict[str, Any]]:
        entries = self.entries()
        done = {e["attempt_id"] for e in entries if e["type"] == "reconcile"}
        return [e for e in entries if e["type"] == "reserve" and e["attempt_id"] not in done
                and (run_id is None or e["run_id"] == run_id)]

    def reconcile_orphans(self, run_id: str) -> int:
        """Reconcile reservations of an interrupted run at their reserved (worst-case) value."""
        orphans = self.outstanding(run_id)
        for e in orphans:
            self.reconcile(attempt_id=e["attempt_id"], usd=float(e["usd"]), basis="worst_case_orphan")
        return len(orphans)
