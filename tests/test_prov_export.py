from __future__ import annotations

import json
from pathlib import Path

import pytest

from habench.prov.export import to_prov_json, write_prov_json
from habench.prov.records import Activity, Agent, Entity, Relation, RelationKind


def _graph() -> list:
    return [
        Agent("urn:uuid:g", "software", {"name": "runner"}),
        Activity(
            "urn:uuid:a", "llm_call", "ok", "2026-01-01T00:00:00.000000Z", None,
            endpoint="bedrock", config={"temperature": 0, "a": [1]}, consumption={"inputTokens": 3},
        ),
        Activity("urn:uuid:b", "prep", "ok", None, None),
        Entity("urn:uuid:in", "prompt", sha256="aa"),
        Entity("urn:uuid:out", "response", sha256="bb", attrs={"n": 1}),
        Relation(RelationKind.USED, "urn:uuid:a", "urn:uuid:in"),
        Relation(RelationKind.WAS_GENERATED_BY, "urn:uuid:out", "urn:uuid:a"),
        Relation(RelationKind.WAS_DERIVED_FROM, "urn:uuid:out", "urn:uuid:in", {"step": "x"}),
        Relation(RelationKind.WAS_ASSOCIATED_WITH, "urn:uuid:a", "urn:uuid:g"),
        Relation(RelationKind.WAS_INFORMED_BY, "urn:uuid:a", "urn:uuid:b"),
    ]


def _js(v: dict) -> dict:
    return {"$": json.dumps(v, sort_keys=True, separators=(",", ":")), "type": "xsd:string"}


def test_exact_prov_json() -> None:
    assert to_prov_json(_graph()) == {
        "prefix": {"habench": "urn:habench:", "uuid": "urn:uuid:"},
        "agent": {"uuid:g": {"prov:type": "habench:software", "habench:attrs": _js({"name": "runner"})}},
        "activity": {
            "uuid:a": {
                "prov:type": "habench:llm_call",
                "habench:status": "ok",
                "prov:startTime": "2026-01-01T00:00:00.000000Z",
                "habench:endpoint": "bedrock",
                "habench:config": _js({"a": [1], "temperature": 0}),
                "habench:code": _js({}),
                "habench:consumption": _js({"inputTokens": 3}),
                "habench:dependencies": _js({}),
                "habench:attrs": _js({}),
            },
            "uuid:b": {
                "prov:type": "habench:prep",
                "habench:status": "ok",
                "habench:config": _js({}),
                "habench:code": _js({}),
                "habench:consumption": _js({}),
                "habench:dependencies": _js({}),
                "habench:attrs": _js({}),
            },
        },
        "entity": {
            "uuid:in": {"prov:type": "habench:prompt", "habench:sha256": "aa", "habench:attrs": _js({})},
            "uuid:out": {"prov:type": "habench:response", "habench:sha256": "bb", "habench:attrs": _js({"n": 1})},
        },
        "used": {"_:r1": {"prov:activity": "uuid:a", "prov:entity": "uuid:in"}},
        "wasGeneratedBy": {"_:r2": {"prov:entity": "uuid:out", "prov:activity": "uuid:a"}},
        "wasDerivedFrom": {
            "_:r3": {"prov:generatedEntity": "uuid:out", "prov:usedEntity": "uuid:in", "habench:step": "x"}
        },
        "wasAssociatedWith": {"_:r4": {"prov:activity": "uuid:a", "prov:agent": "uuid:g"}},
        "wasInformedBy": {"_:r5": {"prov:informed": "uuid:a", "prov:informant": "uuid:b"}},
    }


def test_empty_maps_omitted_and_json_dumps(tmp_path: Path) -> None:
    doc = to_prov_json([Agent("urn:uuid:g", "sw")])
    assert set(doc) == {"prefix", "agent"}
    json.dumps(to_prov_json(_graph()))
    out = tmp_path / "sub" / "p.json"
    write_prov_json(_graph(), out)
    assert json.loads(out.read_text()) == to_prov_json(_graph())


def test_invalid_graph_raises() -> None:
    with pytest.raises(ValueError, match="does not exist"):
        to_prov_json([Relation(RelationKind.USED, "a", "e")])
