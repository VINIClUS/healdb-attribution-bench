"""Per-medication features and group strata (protocol §4.4), from V1 responses and English texts."""

from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import astuple, dataclass, fields
from email.utils import parsedate_to_datetime
from pathlib import Path

from habench.pipeline.mapping import MAP_CAT3_FALLBACK, Hierarchy, who_map

TRAITS = frozenset({"NEGATION", "HYPOTHETICAL", "LOW_CONFIDENCE", "PERTAINS_TO_FAMILY"})
THR_LO, THR_HI = 0.55, 0.70
PHASE_GAP_SECONDS = 3600
V1_PROMPT_LIMIT = 10_000
_PREFIX = "What this medication is indicated for:\n"
_MIDDLE = "\n\nHow this medication works:\n"


@dataclass(frozen=True, slots=True)
class MedFeatures:
    medication: int
    en_len_bin: str
    has_entity: bool
    trait_occ: bool
    multiplicity: bool
    thr_prox: bool
    fallback: bool
    v1_over_10k: bool
    v1_phase: int


def en_len_bin(en: str) -> str:
    n = len(en.strip())
    return "L0" if n < 200 else "L1" if n < 500 else "L2" if n < 1000 else "L3"


def v1_over_10k(en: str) -> bool:
    s = en.strip()
    return len(_PREFIX + s + _MIDDLE + s) > V1_PROMPT_LIMIT


def response_date(raw: str | None):
    """UTC datetime of ResponseMetadata.HTTPHeaders.date, or None when absent."""
    if raw is None:
        return None
    try:
        doc = json.loads(raw)
        d = doc["ResponseMetadata"]["HTTPHeaders"]["date"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    return parsedate_to_datetime(d)


def assign_phases(dates: Mapping[int, object]) -> dict[int, int]:
    """Phases 1, 2, ... of responses sorted by date; a gap > 3600 s starts a new phase. No date: phase 0."""
    out = {m: 0 for m, d in dates.items() if d is None}
    dated = sorted(((d, m) for m, d in dates.items() if d is not None), key=lambda p: (p[0], p[1]))
    phase, prev = 0, None
    for d, m in dated:
        if prev is None or (d - prev).total_seconds() > PHASE_GAP_SECONDS:
            phase += 1
        out[m] = phase
        prev = d
    return out


def response_features(raw: str | None, h: Hierarchy) -> tuple[bool, bool, bool, bool, bool]:
    """(has_entity, trait_occ, multiplicity, thr_prox, fallback) of one raw response."""
    try:
        doc = json.loads(raw) if raw is not None else None
    except json.JSONDecodeError:
        doc = None
    entities = (doc.get("Entities") or []) if isinstance(doc, dict) else []
    trait = thr = fb = False
    codes: Counter[str] = Counter()
    for ent in entities:
        trait |= any(t.get("Name") in TRAITS for t in ent.get("Traits") or [])
        scores = [ent.get("Score")]
        for con in ent.get("ICD10CMConcepts") or []:
            scores.append(con.get("Score"))
            code = con.get("Code")
            if code:
                codes[code] += 1
                fb |= who_map(h, code, "exact_fb")[1] == MAP_CAT3_FALLBACK
        thr |= any(s is not None and THR_LO <= s < THR_HI for s in scores)
    return bool(entities), trait, any(n > 1 for n in codes.values()), thr, fb


def med_features(
    responses: Mapping[int, str | None], texts: Mapping[int, tuple[str, str]], h: Hierarchy
) -> list[MedFeatures]:
    phases = assign_phases({m: response_date(r) for m, r in responses.items()})
    out = []
    for m in sorted(responses):
        en = texts[m][1]
        he, tr, mu, th, fb = response_features(responses[m], h)
        out.append(MedFeatures(m, en_len_bin(en), he, tr, mu, th, fb, v1_over_10k(en), phases[m]))
    return out


def group_strata(groups: Iterable[tuple[str, tuple[int, ...]]], feats: Mapping[int, MedFeatures]) -> dict[str, str]:
    """Stratum per group id: "empty" or f"{en_len_bin of lowest-id member}-P{thr_prox}-M{multiplicity}"."""
    out = {}
    for gid, meds in groups:
        fs = [feats[m] for m in meds]
        if not any(f.has_entity for f in fs):
            out[gid] = "empty"
        else:
            low = feats[min(meds)]
            out[gid] = f"{low.en_len_bin}-P{int(any(f.thr_prox for f in fs))}-M{int(any(f.multiplicity for f in fs))}"
    return out


def load_responses(snap: str = "v1") -> dict[int, str | None]:
    from habench.data.store import load_table

    tab = load_table(snap, "hd_int_med_disease_api_response", ["id_medication", "ds_api_response"])
    return {int(i): t for i, t in zip(tab.column("id_medication").to_pylist(), tab.column("ds_api_response").to_pylist())}


def write_strata(
    path: Path, feats: Mapping[int, MedFeatures], gid_of: Mapping[int, str], stratum_of: Mapping[str, str]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = [f.name for f in fields(MedFeatures)]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow([*names, "group_id", "group_stratum"])
        for m in sorted(feats):
            row = [int(v) if isinstance(v, bool) else v for v in astuple(feats[m])]
            w.writerow([*row, gid_of[m], stratum_of[gid_of[m]]])
