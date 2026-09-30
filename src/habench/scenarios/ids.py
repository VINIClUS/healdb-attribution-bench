"""Opaque identifiers and seeded RNGs, stable across processes (never the built-in `hash`)."""

from __future__ import annotations

import hashlib
import random


def digest(*parts: object) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def stable_int(*parts: object) -> int:
    return int(digest(*parts)[:16], 16)


def rng_for(*parts: object) -> random.Random:
    return random.Random(stable_int(*parts))


def opaque_id(prefix: str, *parts: object, n: int = 12) -> str:
    return prefix + digest(*parts)[:n]
