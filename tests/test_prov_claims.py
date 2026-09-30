from __future__ import annotations

from pathlib import Path

import pytest

from habench.prov.claims import Claim, ClaimLedger
from habench.types import ClaimState


def _claim(state: ClaimState, evidence: tuple[str, ...] = (), limits: str = "", cid: str = "c1") -> Claim:
    return Claim(cid, "subj", "stmt", state, evidence, limits, "2026-01-01T00:00:00.000000Z")


@pytest.mark.parametrize(
    "state", [ClaimState.ARMAZENADO, ClaimState.REDERIVADO_VERIFICADO, ClaimState.REFUTADO]
)
def test_evidence_required(state: ClaimState) -> None:
    with pytest.raises(ValueError, match="evidence"):
        _claim(state)
    _claim(state, evidence=("urn:uuid:e",))


@pytest.mark.parametrize("state", [ClaimState.INFERIDO_COMPATIVEL, ClaimState.NAO_DETERMINADO])
def test_limits_required(state: ClaimState) -> None:
    with pytest.raises(ValueError, match="limits"):
        _claim(state)
    with pytest.raises(ValueError, match="limits"):
        _claim(state, limits="  ")
    _claim(state, limits="only compatible")


def test_current_and_history(tmp_path: Path) -> None:
    ledger = ClaimLedger(tmp_path / "d" / "claims.jsonl")
    assert ledger.current() == {}
    v1 = _claim(ClaimState.INFERIDO_COMPATIVEL, limits="guess")
    v2 = _claim(ClaimState.REDERIVADO_VERIFICADO, evidence=("e1", "e2"))
    other = _claim(ClaimState.NAO_DETERMINADO, limits="unknown", cid="c2")
    for c in (v1, other, v2):
        ledger.record(c)
    assert ledger.history("c1") == [v1, v2]
    assert ledger.history("nope") == []
    assert ledger.current() == {"c1": v2, "c2": other}
    assert len(ledger.path.read_text().splitlines()) == 3
