"""Claim ledger (§6.5): reconstructed claims with state, evidence and limits."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from habench.prov.scrub import assert_clean, scrub
from habench.prov.store import append_json_lines, read_json_lines
from habench.types import ClaimState

_NEEDS_EVIDENCE = {ClaimState.ARMAZENADO, ClaimState.REDERIVADO_VERIFICADO, ClaimState.REFUTADO}
_NEEDS_LIMITS = {ClaimState.INFERIDO_COMPATIVEL, ClaimState.NAO_DETERMINADO}


@dataclass(frozen=True, slots=True)
class Claim:
    id: str
    subject: str
    statement: str
    state: ClaimState
    evidence: tuple[str, ...]
    limits: str
    recorded: str

    def __post_init__(self) -> None:
        if self.state in _NEEDS_EVIDENCE and not self.evidence:
            raise ValueError(f"claim state {self.state} requires evidence")
        if self.state in _NEEDS_LIMITS and not self.limits.strip():
            raise ValueError(f"claim state {self.state} requires limits")


def _to_dict(c: Claim) -> dict[str, Any]:
    return {
        "id": c.id,
        "subject": c.subject,
        "statement": c.statement,
        "state": str(c.state),
        "evidence": list(c.evidence),
        "limits": c.limits,
        "recorded": c.recorded,
    }


def _from_dict(d: dict[str, Any]) -> Claim:
    return Claim(**{**d, "state": ClaimState(d["state"]), "evidence": tuple(d["evidence"])})


class ClaimLedger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, claim: Claim) -> None:
        d = scrub(_to_dict(claim))
        assert_clean(d)
        append_json_lines(self.path, [d])

    def _all(self) -> list[Claim]:
        return [_from_dict(d) for d in read_json_lines(self.path)]

    def history(self, claim_id: str) -> list[Claim]:
        return [c for c in self._all() if c.id == claim_id]

    def current(self) -> dict[str, Claim]:
        return {c.id: c for c in self._all()}  # later versions overwrite earlier ones
