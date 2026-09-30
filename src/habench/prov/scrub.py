"""Credential scrubbing: credentials or auth headers must never be stored."""

from __future__ import annotations

import re
from typing import Any

from habench.prov.records import Record, from_dict, to_dict

REDACTED = "[REDACTED]"

_EXACT_KEYS = frozenset(
    {
        "authorization",
        "proxy_authorization",
        "token",
        "x_amz_security_token",
        "cookie",
        "set_cookie",
        "x_api_key",
    }
)
_KEY_SUBSTRINGS = (
    "secret",
    "password",
    "passwd",
    "credential",
    "session_token",
    "sessiontoken",
    "security_token",
    "securitytoken",
    "access_key",
    "accesskey",
    "api_key",
    "apikey",
    "private_key",
)
_VALUE_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
        r"AWS4-HMAC-SHA256\s+Credential=",
        r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}",
        r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"(?i)\b(?:password|passwd|pwd)\s*[=:]\s*\S{4,}",
    )
)


class SecretLeak(ValueError):
    """Sensitive content found where it must not be stored."""


def is_sensitive_key(key: object) -> bool:
    k = str(key).lower().replace("-", "_")
    return k in _EXACT_KEYS or any(s in k for s in _KEY_SUBSTRINGS)


def is_sensitive_value(value: object) -> bool:
    return isinstance(value, str) and any(p.search(value) for p in _VALUE_PATTERNS)


def scrub(obj: Any) -> Any:
    """Deep copy with sensitive keys' values and sensitive strings redacted."""
    if isinstance(obj, dict):
        return {k: REDACTED if is_sensitive_key(k) else scrub(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(scrub(v) for v in obj)
    if is_sensitive_value(obj):
        return REDACTED
    return obj


def scrub_record(record: Record) -> Record:
    return from_dict(scrub(to_dict(record)))


def find_secrets(obj: Any, path: str = "$") -> list[str]:
    if isinstance(obj, dict):
        out: list[str] = []
        for k, v in obj.items():
            here = f"{path}.{k}"
            if is_sensitive_key(k):
                if v != REDACTED:
                    out.append(here)
            else:
                out.extend(find_secrets(v, here))
        return out
    if isinstance(obj, (list, tuple)):
        return [loc for i, v in enumerate(obj) for loc in find_secrets(v, f"{path}[{i}]")]
    return [path] if is_sensitive_value(obj) else []


def assert_clean(obj: Any) -> None:
    if isinstance(obj, (dict, list, tuple, str)) or obj is None:
        data = obj
    else:
        data = to_dict(obj)
    locations = find_secrets(data)
    if locations:
        raise SecretLeak("sensitive content at: " + ", ".join(locations))


def assert_clean_bytes(data: bytes) -> None:
    """Check raw bytes (stored verbatim, so checked, never modified)."""
    text = data.decode("utf-8", errors="replace")
    hits = [p.pattern for p in _VALUE_PATTERNS if p.search(text)]
    if hits:
        raise SecretLeak("sensitive patterns in raw bytes: " + ", ".join(hits))
