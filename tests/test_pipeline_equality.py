import json

from habench.pipeline import equality as eq


def _resp(**kw) -> str:
    return json.dumps(kw)


def test_metadata_removed_top_level_only():
    raw = _resp(
        Entities=[{"ResponseMetadata": {"x": 1}}],
        ModelVersion="0.1.0",
        ResponseMetadata={"RequestId": "a"},
    )
    content = eq.extraction_content(raw)
    assert "ResponseMetadata" not in content
    assert content["ModelVersion"] == "0.1.0"
    assert content["Entities"][0]["ResponseMetadata"] == {"x": 1}


def test_top_level_must_be_object():
    import pytest

    with pytest.raises(ValueError):
        eq.extraction_content("[1]")


def test_entity_order_matters_key_order_does_not():
    a = '{"Entities":[{"Text":"a"},{"Text":"b"}],"ModelVersion":"1"}'
    b = '{"ModelVersion":"1","Entities":[{"Text":"a"},{"Text":"b"}]}'
    c = '{"Entities":[{"Text":"b"},{"Text":"a"}],"ModelVersion":"1"}'
    d = '{"Entities":[{"Text":"a"},{"Text":"b"}],"ModelVersion":"2"}'
    assert eq.equal_level2(a, b)
    assert not eq.equal_level2(a, c)
    assert not eq.equal_level2(a, d)


def test_float_repr_differs():
    assert not eq.equal_level2('{"S":0.1}', '{"S":0.10000000000000002}')
    assert eq.equal_level2('{"S":0.1}', '{"S": 0.10}')


def test_level1_differs_on_request_id_only():
    a = '{"Entities":[],"ResponseMetadata":{"RequestId":"1"}}'
    b = '{"Entities":[],"ResponseMetadata":{"RequestId":"2"}}'
    assert not eq.equal_level1(a, b)
    assert eq.equal_level2(a, b)
    assert eq.equal_level1(a, a) and eq.equal_level1(a, a.encode())
    assert eq.level2_digest(a) == eq.level2_digest(b)


def test_canonical_json_keeps_unicode_and_rejects_nan():
    import pytest

    assert eq.canonical_json({"b": "é", "a": [2, 1]}) == '{"a":[2,1],"b":"é"}'
    with pytest.raises(ValueError):
        eq.canonical_json({"a": float("nan")})


def test_level3():
    a = {(1, "A"): {"s": 1.0}, (1, "B"): {"s": 2.0}, (2, "C"): {"s": 3.0}}
    b = {(1, "A"): {"s": 1.0}, (1, "B"): {"s": 2.5}, (3, "D"): {"s": 3.0}}
    assert eq.equal_level3(a, dict(a))
    assert not eq.equal_level3(a, b)
    assert eq.level3_diff(a, b) == {
        "only_a": [(2, "C")],
        "only_b": [(3, "D")],
        "attr_differ": [(1, "B")],
    }
