"""On-disk layout of views and of the truth-side keys (SPEC §7.1, §11.2). Shared by the view builder and the broker.

A view directory holds only uniformly named files and a manifest:

    <HAB_DATA_DIR>/views/<partition>/<vid>/manifest.json
    <HAB_DATA_DIR>/views/<partition>/<vid>/<ref>.bin

- `vid` and every `ref` are HMAC-SHA256 ids under a key kept only under `<HAB_DATA_DIR>/truth/` (never in a view).
- The manifest lists artifacts in a shuffled order; files carry a constant mtime.
- The broker's side of the view (contrast id, view name, capability-independent handle map) lives in the truth
  directory: `<HAB_DATA_DIR>/truth/<partition>/views/<vid>.json`.

This module is imported by the method process (to read a manifest), so it must not import `habench.pipeline`,
`habench.oracle` or `habench.scenarios`, and it never reads the key itself unless asked by trusted code.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from habench.types import SealedError

DATA_DIR = Path(os.environ.get("HAB_DATA_DIR", "/home/vinicius/hab-data"))
PARTITIONS = ("dev", "cal")  # the only partitions that may be materialized before the freeze
CONSTANT_MTIME = 946684800  # 2000-01-01T00:00:00Z
MANIFEST = "manifest.json"


def views_root(partition: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / "views" / check_partition(partition)


def truth_root(data_dir: Path = DATA_DIR) -> Path:
    return data_dir / "truth"


def check_partition(partition: str) -> str:
    if partition == "test":
        raise SealedError("views of the test partition are never materialized before the freeze")
    if partition not in PARTITIONS:
        raise ValueError(f"unknown partition {partition!r}")
    return partition


def load_key(data_dir: Path = DATA_DIR, *, create: bool = False) -> bytes:
    """The HMAC key under the truth directory. Trusted code only (runner, view builder, broker)."""
    path = truth_root(data_dir) / "hmac.key"
    if not path.exists():
        if not create:
            raise FileNotFoundError(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(secrets.token_bytes(32))
        path.chmod(0o600)
    return path.read_bytes()


def hid(key: bytes, *parts: str, n: int = 16) -> str:
    """Hex HMAC-SHA256 id of the joined parts, truncated to n hex chars."""
    return hmac.new(key, "\x1f".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()[:n]


def patch_handle(key: bytes, cid: str, factor: str) -> str:
    """Opaque `ev:<hmac8>` handle of a patch factor of a contrast (SPEC 4.5)."""
    return "ev:" + hid(key, "patch", cid, factor, n=8)


@dataclass(frozen=True, slots=True)
class Entry:
    ref: str  # "a" + hmac12
    kind: str  # SPEC 7.1 kind, or acm_response_top1 / trace_winners
    run: str  # "x0" | "x1" | ""
    sha256: str

    @property
    def file(self) -> str:
        return self.ref + ".bin"


@dataclass(frozen=True, slots=True)
class Manifest:
    vid: str
    entries: tuple[Entry, ...]

    def to_json(self) -> str:
        obj = {"vid": self.vid, "artifacts": [[e.ref, e.kind, e.run, e.sha256] for e in self.entries]}
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> Manifest:
        obj = json.loads(text)
        return cls(obj["vid"], tuple(Entry(*a) for a in obj["artifacts"]))


def read_manifest(view_dir: Path) -> Manifest:
    return Manifest.from_json((view_dir / MANIFEST).read_text(encoding="utf-8"))


@dataclass(frozen=True, slots=True)
class BrokerSide:
    """Truth-side record of one materialized view: what the broker needs, never mounted for methods."""

    vid: str
    partition: str
    cid: str
    view: str  # e.g. "L2-R", "L2-M-A6", "N1"
    handles: tuple[tuple[str, str], ...]  # (handle, D member) for patches: ("ev:1a2b3c4d", "patch:p1")

    def to_json(self) -> str:
        return json.dumps(
            {"vid": self.vid, "partition": self.partition, "cid": self.cid, "view": self.view,
             "handles": [list(h) for h in self.handles]},
            sort_keys=True, separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, text: str) -> BrokerSide:
        o = json.loads(text)
        return cls(o["vid"], o["partition"], o["cid"], o["view"], tuple((h, f) for h, f in o["handles"]))


def public_level(level: object) -> str:
    """Public string of a config level: floats in repr form ("0.6"), booleans lower-case, others as str."""
    if isinstance(level, bool):
        return str(level).lower()
    return repr(level) if isinstance(level, float) else str(level)


def public_config(items: Iterable[tuple[str, object]]) -> dict[str, str]:
    """The declared/executed config in the public schema of `Env.config` (SPEC 11.1): never patch items (4.5)."""
    return {n: public_level(v) for n, v in items if not n.startswith("patch:")}


def broker_side_path(partition: str, vid: str, data_dir: Path = DATA_DIR) -> Path:
    return truth_root(data_dir) / check_partition(partition) / "views" / f"{vid}.json"
