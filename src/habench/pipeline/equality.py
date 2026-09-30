"""Three equality levels for ACM responses and extracted tables (protocol 5.2)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

TRANSPORT_METADATA_KEYS: tuple[str, ...] = ("ResponseMetadata",)


def raw_sha256(raw: str | bytes) -> str:
    data = raw.encode("utf-8", errors="surrogateescape") if isinstance(raw, str) else raw
    return hashlib.sha256(data).hexdigest()


def equal_level1(a: str | bytes, b: str | bytes) -> bool:
    """Exact bytes."""
    return raw_sha256(a) == raw_sha256(b)


def extraction_content(raw: str) -> object:
    """Parsed response without the top-level transport metadata keys."""
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("response top level is not a JSON object")
    return {k: v for k, v in obj.items() if k not in TRANSPORT_METADATA_KEYS}


def canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def level2_digest(raw: str) -> str:
    return raw_sha256(canonical_json(extraction_content(raw)))


def equal_level2(a: str, b: str) -> bool:
    return level2_digest(a) == level2_digest(b)


def equal_level3(a: Mapping[Any, Any], b: Mapping[Any, Any]) -> bool:
    """Decision level: same key set and exactly equal attribute values."""
    return a.keys() == b.keys() and all(a[k] == b[k] for k in a)


def level3_diff(a: Mapping[Any, Any], b: Mapping[Any, Any]) -> dict[str, list]:
    return {
        "only_a": sorted(a.keys() - b.keys()),
        "only_b": sorted(b.keys() - a.keys()),
        "attr_differ": sorted(k for k in a.keys() & b.keys() if a[k] != b[k]),
    }
