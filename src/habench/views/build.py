"""Per-case evidence views (SPEC 7.1-7.2, 11.2) in the on-disk layout of `habench.views.layout`.

Trusted, truth-side code: it imports the pipeline and the oracle and is never loaded by a method process.

One file per (kind, run); run is "x0"/"x1" for run-specific kinds and "" for run-independent ones. Contents are
canonical JSON, except `acm_response`/`acm_response_top1`, which store the raw response strings per medication.

Simplifications, all documented in SPEC terms:
- the deterministic core has no operational actions: `ops_actions` is always an empty list;
- hybrids are executed on `evidence` alone (no stored responses for other preparation combinations), so x0 and x1
  responses differ only by the contrast's patches;
- N1/N2 `final` is the same presence map as in the L views, tagged with the historical schema name.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import random
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path

import numpy as np

from habench.methods.base import PresenceMap
from habench.oracle.contrast import Contrast
from habench.oracle.hybrids import Hybrids
from habench.pipeline import tables_v1, tables_v2
from habench.pipeline.core import RunResult
from habench.pipeline.evidence import STATUS_FAILED, STATUS_MISSING, Evidence, apply_edits
from habench.pipeline.mapping import Hierarchy
from habench.pipeline.trace import Trace
from habench.types import AssocKey
from habench.views.layout import (
    CONSTANT_MTIME,
    MANIFEST,
    BrokerSide,
    Entry,
    Manifest,
    broker_side_path,
    check_partition,
    hid,
    patch_handle,
    public_config,
    views_root,
)
from habench.views.profiles import kinds, split_view

RUNS = ("x0", "x1")
RUN_INDEPENDENT = frozenset({"source_pt", "env_versions", "ops_actions"})
HASHED = ("submitted_text", "translation_en", "acm_response", "final")  # SPEC 7.1 `hashes`
SCHEMAS = {"N1": "md_v1", "N2": "md_v2"}


@dataclass(frozen=True)
class Texts:
    """Public inputs of the pipeline for one medication."""

    source_pt: str
    translation_en: str
    submitted_text: str


def canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _plain(obj: object) -> object:
    """Dataclasses as dicts with every field, AssocKey as [med, system, version, code], tuples as lists."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, AssocKey):
        return [obj.med, obj.system, obj.version, obj.code]
    if is_dataclass(obj):
        return {f.name: _plain(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, (tuple, list, frozenset)):
        return [_plain(x) for x in obj]
    raise TypeError(f"not serializable in a view: {type(obj).__name__}")


def _trace_json(tr: Trace) -> dict:
    return {
        "candidates": _plain(tr.candidates),
        "records": _plain(tr.records),
        "decisions": _plain(tr.decisions),
    }


def _winners_json(tr: Trace) -> list[dict]:
    """SPEC 7.2 A6: per approved record (every decision passes), its source candidate and its decisions."""
    by_rid: dict[int, list] = {}
    for d in tr.decisions:
        by_rid.setdefault(d.ref, []).append(d)
    cands = {c.cid: c for c in tr.candidates}
    out = []
    for r in tr.records:
        decisions = by_rid.get(r.rid, [])
        if not decisions or not all(d.verdict for d in decisions):
            continue
        rec = {k: v for k, v in _plain(r).items() if k not in ("members", "source")}
        out.append({"record": rec, "source": _plain(cands[r.source]), "decisions": _plain(decisions)})
    return out


def _raw_responses(evidence: Evidence, meds: tuple[int, ...]) -> dict[int, str | None]:
    raw = evidence._cache.get("_base", evidence)._raw  # original strings, never patched
    return {m: raw.get(m) for m in meds}


def _patched_raw(contrast: Contrast, raw: Mapping[int, str | None]) -> dict[int, str | None]:
    """x1 responses: the contrast's patches applied to the parsed JSON (key order kept), untouched meds as stored."""
    out = dict(raw)
    for med, text in raw.items():
        edits = [e for p in sorted(contrast.patches, key=lambda p: p.id) for e in p.edits if e.med == med]
        if not edits:
            continue
        if text is None:
            raise ValueError(f"patch on medication {med} without a stored response")
        out[med] = json.dumps(apply_edits(json.loads(text), edits), ensure_ascii=False)
    return out


def _top1(text: str | None) -> str | None:
    if text is None:
        return None
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(doc, dict):
        for ent in doc.get("Entities") or []:
            if isinstance(ent, dict) and isinstance(ent.get("ICD10CMConcepts"), list):
                ent["ICD10CMConcepts"] = ent["ICD10CMConcepts"][:1]
    return json.dumps(doc, ensure_ascii=False)


def _final_json(res: RunResult, schema: str | None) -> dict:
    unavailable = [m for m, st in res.status.items() if st in (STATUS_FAILED, STATUS_MISSING)]
    obj = PresenceMap(res.present, unavailable).to_json()
    if schema:
        obj["schema"] = schema
    return obj


class _Content:
    """Lazy artifact contents of one contrast: (kind, run) -> bytes, shared by every view of the contrast."""

    def __init__(self, contrast: Contrast, evidence: Evidence, hier: Hierarchy, texts: Mapping[int, Texts]) -> None:
        self.c = contrast
        self.hier = hier
        self.texts = {m: texts[m] for m in contrast.meds}
        self.hyb = Hybrids(contrast, evidence, hier)
        raw0 = _raw_responses(evidence, contrast.meds)
        self.raw = {"x0": raw0, "x1": _patched_raw(contrast, raw0)}
        self._cache: dict[tuple[str, str, str | None], bytes] = {}

    def _run(self, run: str, *, trace: bool = False) -> RunResult:
        S = frozenset(self.hyb.D) if run == "x1" else frozenset()
        return self.hyb.run(S, trace=trace)

    def get(self, kind: str, run: str, schema: str | None = None) -> bytes:
        key = (kind, run, schema)
        if key not in self._cache:
            self._cache[key] = self._make(kind, run, schema)
        return self._cache[key]

    def _make(self, kind: str, run: str, schema: str | None) -> bytes:
        c = self.c
        x = c.x1 if run == "x1" else c.x0
        d = c.d1 if run == "x1" else c.d0
        if kind == "source_pt":
            return canonical({str(m): t.source_pt for m, t in self.texts.items()})
        if kind == "translation_en":
            return canonical({str(m): t.translation_en for m, t in self.texts.items()})
        if kind == "submitted_text":
            return canonical({str(m): t.submitted_text for m, t in self.texts.items()})
        if kind == "final":
            return canonical(_final_json(self._run(run), SCHEMAS.get(schema or "")))
        if kind == "config_declared":
            return canonical({"config": public_config(d.items)})
        if kind == "code_link":
            return canonical({"executed": public_config(x.items)})
        if kind == "env_versions":
            return canonical({"hierarchy": self.hier.version, "python": platform.python_version(),
                              "numpy": np.__version__})
        if kind == "ops_actions":
            return canonical({"actions": []})
        if kind == "acm_response":
            return canonical({str(m): t for m, t in self.raw[run].items()})
        if kind == "acm_response_top1":
            return canonical({str(m): _top1(t) for m, t in self.raw[run].items()})
        if kind == "trace":
            if schema == "N1":
                pairs = list(self.raw[run].items())
                return canonical({"entity": tables_v1.entity_rows(pairs), "trait": tables_v1.trait_rows(pairs)})
            if schema == "N2":
                pairs = list(self.raw[run].items())
                icd, trait = tables_v2.entity_icd_rows(pairs), tables_v2.entity_trait_rows(pairs)
                return canonical({"entity_icd": icd, "entity_trait": trait,
                                  "cutoff_audit": tables_v2.cutoff_audit_rows(icd, trait, self.hier)})
            return canonical(_trace_json(self._run(run, trace=True).trace))
        if kind == "trace_winners":
            return canonical(_winners_json(self._run(run, trace=True).trace))
        if kind == "hashes":
            return canonical({k: hashlib.sha256(self.get(k, run)).hexdigest() for k in HASHED})
        raise ValueError(f"unknown artifact kind {kind!r}")


def _write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.utime(tmp, (CONSTANT_MTIME, CONSTANT_MTIME))
    os.replace(tmp, path)


def build_view(
    contrast: Contrast,
    view: str,
    *,
    evidence: Evidence,
    hier: Hierarchy,
    texts: Mapping[int, Texts],
    partition: str,
    key: bytes,
    data_dir: Path,
) -> tuple[Path, BrokerSide]:
    """Materialize `view` of `contrast`; returns the view directory and the broker's side record.

    Refuses the test partition before touching the disk. Idempotent: rebuilding yields byte-identical files.
    """
    check_partition(partition)
    wanted = kinds(view)  # ValueError for an unknown view or an absent ablated item
    base = split_view(view)[0]
    schema = base if base in SCHEMAS else None
    content = _Content(contrast, evidence, hier, texts)

    vid = hid(key, "view", contrast.cid, view)
    view_dir = views_root(partition, data_dir) / vid
    view_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    blobs: dict[str, bytes] = {}
    for kind in sorted(wanted):
        for run in ("",) if kind in RUN_INDEPENDENT else RUNS:
            data = content.get(kind, run or "x0", schema)
            ref = "a" + hid(key, "ref", vid, kind, run, n=12)
            entries.append(Entry(ref, kind, run, hashlib.sha256(data).hexdigest()))
            blobs[ref] = data
    random.Random(int(hid(key, "order", vid), 16)).shuffle(entries)

    for e in entries:
        _write(view_dir / e.file, blobs[e.ref])
    _write(view_dir / MANIFEST, Manifest(vid, tuple(entries)).to_json().encode("utf-8"))
    keep = {e.file for e in entries} | {MANIFEST}
    for p in view_dir.iterdir():
        if p.name not in keep:
            p.unlink()
    os.utime(view_dir, (CONSTANT_MTIME, CONSTANT_MTIME))

    handles = tuple(sorted((patch_handle(key, contrast.cid, f), f) for f in contrast.D if f.startswith("patch:")))
    side = BrokerSide(vid, partition, contrast.cid, view, handles)
    side_path = broker_side_path(partition, vid, data_dir)
    side_path.parent.mkdir(parents=True, exist_ok=True)
    side_path.write_text(side.to_json(), encoding="utf-8")
    return view_dir, side
