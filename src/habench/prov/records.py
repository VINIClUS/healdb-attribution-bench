"""PROV-DM-compatible provenance records (protocol §6.5).

Identity is always a fresh URN; content hashes are attributes, never identities.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def new_id() -> str:
    return f"urn:uuid:{uuid.uuid4()}"


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class RelationKind(StrEnum):
    USED = "used"
    WAS_GENERATED_BY = "wasGeneratedBy"
    WAS_DERIVED_FROM = "wasDerivedFrom"
    WAS_ASSOCIATED_WITH = "wasAssociatedWith"
    WAS_INFORMED_BY = "wasInformedBy"


@dataclass(frozen=True, slots=True)
class Entity:
    id: str
    kind: str
    sha256: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Activity:
    id: str
    kind: str
    status: str
    started: str | None
    ended: str | None
    endpoint: str | None = None
    region: str | None = None
    model_returned: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    code: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    consumption: dict[str, Any] = field(default_factory=dict)
    dependencies: dict[str, Any] = field(default_factory=dict)
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Agent:
    id: str
    kind: str
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Relation:
    kind: RelationKind
    subject: str
    object: str
    attrs: dict[str, Any] = field(default_factory=dict)


Record = Entity | Activity | Agent | Relation

_CLASSES: dict[str, type] = {
    "entity": Entity,
    "activity": Activity,
    "agent": Agent,
    "relation": Relation,
}
_NAMES = {cls: name for name, cls in _CLASSES.items()}

# relation kind -> (subject type, object type)
_ENDPOINTS: dict[RelationKind, tuple[type, type]] = {
    RelationKind.USED: (Activity, Entity),
    RelationKind.WAS_GENERATED_BY: (Entity, Activity),
    RelationKind.WAS_DERIVED_FROM: (Entity, Entity),
    RelationKind.WAS_ASSOCIATED_WITH: (Activity, Agent),
    RelationKind.WAS_INFORMED_BY: (Activity, Activity),
}


def to_dict(record: Record) -> dict[str, Any]:
    out: dict[str, Any] = {"record": _NAMES[type(record)]}
    for f in fields(record):
        value = getattr(record, f.name)
        out[f.name] = str(value) if isinstance(value, RelationKind) else value
    return out


def from_dict(d: dict[str, Any]) -> Record:
    data = dict(d)
    cls = _CLASSES[data.pop("record")]
    if cls is Relation:
        data["kind"] = RelationKind(data["kind"])
    return cls(**data)


def validate(records: Iterable[Record]) -> list[str]:
    records = list(records)
    problems: list[str] = []
    nodes: dict[str, Record] = {}
    for r in records:
        if isinstance(r, Relation):
            continue
        if r.id in nodes:
            problems.append(f"duplicate id: {r.id}")
        else:
            nodes[r.id] = r
    for r in records:
        if not isinstance(r, Relation):
            continue
        want_subject, want_object = _ENDPOINTS[r.kind]
        for role, ident, want in (("subject", r.subject, want_subject), ("object", r.object, want_object)):
            node = nodes.get(ident)
            if node is None:
                problems.append(f"{r.kind} {role} does not exist: {ident}")
            elif not isinstance(node, want):
                problems.append(
                    f"{r.kind} {role} {ident} must be {_NAMES[want]}, got {_NAMES[type(node)]}"
                )
    return problems
