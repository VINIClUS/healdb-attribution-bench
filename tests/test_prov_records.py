from __future__ import annotations

import hashlib
import json

from hypothesis import given
from hypothesis import strategies as st

from habench.prov.records import (
    Activity,
    Agent,
    Entity,
    Relation,
    RelationKind,
    from_dict,
    new_id,
    to_dict,
    utc_now,
    validate,
)

json_scalars = st.none() | st.booleans() | st.integers(-1000, 1000) | st.text(max_size=8)
json_values = st.recursive(
    json_scalars,
    lambda c: st.lists(c, max_size=3) | st.dictionaries(st.text(max_size=5), c, max_size=3),
    max_leaves=8,
)
attrs_st = st.dictionaries(st.text(max_size=5), json_values, max_size=4)


def test_new_id_and_utc_now_format() -> None:
    a, b = new_id(), new_id()
    assert a != b and a.startswith("urn:uuid:")
    assert len(a) == len("urn:uuid:") + 36
    ts = utc_now()
    assert ts.endswith("Z") and "." in ts


def test_identical_content_gets_distinct_ids_and_id_is_not_hash() -> None:
    content = b"same"
    digest = hashlib.sha256(content).hexdigest()
    e1 = Entity(new_id(), "response", sha256=digest)
    e2 = Entity(new_id(), "response", sha256=digest)
    assert e1.id != e2.id
    assert e1.id != digest and digest not in e1.id
    a1 = Activity(new_id(), "call", "ok", None, None)
    a2 = Activity(new_id(), "call", "ok", None, None)
    assert a1.id != a2.id


@given(attrs=attrs_st, cfg=attrs_st, err=st.none() | attrs_st)
def test_round_trip_property(attrs: dict, cfg: dict, err: dict | None) -> None:
    records = [
        Entity("urn:uuid:e", "x", sha256="ab", attrs=attrs),
        Activity("urn:uuid:a", "call", "ok", "t0", "t1", config=cfg, error=err, attrs=attrs),
        Agent("urn:uuid:g", "software", attrs=attrs),
        Relation(RelationKind.USED, "urn:uuid:a", "urn:uuid:e", attrs=attrs),
    ]
    for r in records:
        d = to_dict(r)
        assert d["record"] in {"entity", "activity", "agent", "relation"}
        assert from_dict(json.loads(json.dumps(d))) == r


def test_validate_ok_and_problems() -> None:
    ag, ac, e1, e2 = Agent("g", "sw"), Activity("a", "c", "ok", None, None), Entity("e1", "k"), Entity("e2", "k")
    good = [
        ag, ac, e1, e2,
        Relation(RelationKind.USED, "a", "e1"),
        Relation(RelationKind.WAS_GENERATED_BY, "e2", "a"),
        Relation(RelationKind.WAS_DERIVED_FROM, "e2", "e1"),
        Relation(RelationKind.WAS_ASSOCIATED_WITH, "a", "g"),
    ]
    assert validate(good) == []
    assert any("does not exist" in p for p in validate([ac, Relation(RelationKind.USED, "a", "nope")]))
    assert any("must be entity" in p for p in validate([ac, ag, Relation(RelationKind.USED, "a", "g")]))
    assert any("must be activity" in p for p in validate([e1, e2, Relation(RelationKind.WAS_GENERATED_BY, "e1", "e2")]))
    assert any("duplicate" in p for p in validate([e1, Entity("e1", "other")]))
    other = Activity("b", "c", "ok", None, None)
    assert validate([ac, other, Relation(RelationKind.WAS_INFORMED_BY, "a", "b")]) == []
