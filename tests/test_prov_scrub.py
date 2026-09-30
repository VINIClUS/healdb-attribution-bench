from __future__ import annotations

import pytest

from habench.prov.records import Activity, Entity
from habench.prov.scrub import (
    REDACTED,
    SecretLeak,
    assert_clean,
    assert_clean_bytes,
    find_secrets,
    is_sensitive_key,
    scrub,
    scrub_record,
)

AKIA = "AKIA" + "A" * 16
SIGV4 = "AWS4-HMAC-SHA256 Credential=" + AKIA + "/20260101/us-east-1/bedrock/aws4_request"

SENSITIVE_KEYS = [
    "Authorization", "Proxy-Authorization", "token", "X-Amz-Security-Token", "Cookie", "Set-Cookie",
    "x-api-key", "client_secret", "DB_PASSWORD", "passwd", "aws_credentials", "session_token",
    "security_token", "aws_access_key_id", "api_key", "ApiKey", "private_key",
    "SecurityToken", "SessionToken", "AccessKeyId", "SecretAccessKey",
]
SAFE_KEYS = ["inputTokens", "outputTokens", "PaginationToken", "x-amzn-RequestId", "date", "totalTokens"]

SENSITIVE_VALUES = [
    AKIA,
    "ASIA" + "B" * 16,
    SIGV4,
    "Bearer " + "abcdefgh12345",
    "sk-" + "a" * 24,
    "sk-ant-" + "b" * 24,
    "-----BEGIN RSA " + "PRIVATE KEY-----",
    "pass" + "word=" + "hunter22",
    "PWD: " + "abcd1234",
]


@pytest.mark.parametrize("key", SENSITIVE_KEYS)
def test_sensitive_keys(key: str) -> None:
    assert is_sensitive_key(key)


@pytest.mark.parametrize("key", SAFE_KEYS)
def test_safe_keys(key: str) -> None:
    assert not is_sensitive_key(key)
    assert scrub({key: "v"}) == {key: "v"}


@pytest.mark.parametrize("value", SENSITIVE_VALUES)
def test_sensitive_values_nested(value: str) -> None:
    obj = {"a": [1, {"b": ("x", value)}], "note": f"prefix {value} suffix"}
    out = scrub(obj)
    assert out == {"a": [1, {"b": ("x", REDACTED)}], "note": REDACTED}
    assert find_secrets(obj) == ["$.a[1].b[1]", "$.note"]
    assert find_secrets(out) == []
    assert_clean(out)
    with pytest.raises(SecretLeak):
        assert_clean(obj)


def test_sensitive_key_value_redacted_even_if_dict() -> None:
    out = scrub({"headers": {"Authorization": {"k": "v"}, "date": "d"}})
    assert out == {"headers": {"Authorization": REDACTED, "date": "d"}}
    assert find_secrets({"Authorization": "x"}) == ["$.Authorization"]


def test_scrub_does_not_mutate_input() -> None:
    obj = {"token": "abc", "l": [SIGV4]}
    scrub(obj)
    assert obj["token"] == "abc"


def test_scrub_record_and_assert_clean_record() -> None:
    act = Activity("a", "call", "ok", None, None, config={"headers": {"Authorization": SIGV4}}, attrs={"k": AKIA})
    with pytest.raises(SecretLeak):
        assert_clean(act)
    clean = scrub_record(act)
    assert isinstance(clean, Activity)
    assert clean.config == {"headers": {"Authorization": REDACTED}}
    assert clean.attrs == {"k": REDACTED}
    assert_clean(clean)
    assert scrub_record(Entity("e", "k")) == Entity("e", "k")


def test_assert_clean_bytes() -> None:
    with pytest.raises(SecretLeak):
        assert_clean_bytes(b'{"x": "' + AKIA.encode() + b'"}')
    with pytest.raises(SecretLeak):
        assert_clean_bytes(b"\xff\xfe " + SIGV4.encode())
    assert_clean_bytes(b'{"inputTokens": 3, "text": "hello"}')
