"""W3C PROV-JSON export (submission layout), no external dependency."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import fields
from pathlib import Path
from typing import Any

from habench.prov.records import Activity, Agent, Entity, Record, Relation, RelationKind, validate

_ROLES: dict[RelationKind, tuple[str, str]] = {
    RelationKind.USED: ("prov:activity", "prov:entity"),
    RelationKind.WAS_GENERATED_BY: ("prov:entity", "prov:activity"),
    RelationKind.WAS_DERIVED_FROM: ("prov:generatedEntity", "prov:usedEntity"),
    RelationKind.WAS_ASSOCIATED_WITH: ("prov:activity", "prov:agent"),
    RelationKind.WAS_INFORMED_BY: ("prov:informed", "prov:informant"),
}
_TIME_FIELDS = {"started": "prov:startTime", "ended": "prov:endTime"}


def _qname(ident: str) -> str:
    return "uuid:" + ident[len("urn:uuid:") :] if ident.startswith("urn:uuid:") else ident


def _value(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        text = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return {"$": text, "type": "xsd:string"}
    return v


def _node(record: Entity | Activity | Agent) -> dict[str, Any]:
    out: dict[str, Any] = {"prov:type": f"habench:{record.kind}"}
    for f in fields(record):
        if f.name in ("id", "kind"):
            continue
        v = getattr(record, f.name)
        if v is None:
            continue
        out[_TIME_FIELDS.get(f.name, f"habench:{f.name}")] = _value(v)
    return out


def to_prov_json(records: Iterable[Record]) -> dict[str, Any]:
    records = list(records)
    problems = validate(records)
    if problems:
        raise ValueError("invalid provenance graph: " + "; ".join(problems))
    doc: dict[str, Any] = {"prefix": {"habench": "urn:habench:", "uuid": "urn:uuid:"}}
    n = 0
    for r in records:
        if isinstance(r, Relation):
            n += 1
            subj_role, obj_role = _ROLES[r.kind]
            body = {subj_role: _qname(r.subject), obj_role: _qname(r.object)}
            body.update({f"habench:{k}": _value(v) for k, v in r.attrs.items()})
            doc.setdefault(str(r.kind), {})[f"_:r{n}"] = body
        else:
            section = type(r).__name__.lower()
            doc.setdefault(section, {})[_qname(r.id)] = _node(r)
    return doc


def write_prov_json(records: Iterable[Record], path: Path) -> None:
    doc = to_prov_json(records)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
