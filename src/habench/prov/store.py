"""Append-only JSONL provenance store with exclusive file locking."""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from habench.prov.records import Record, from_dict, to_dict
from habench.prov.scrub import assert_clean, scrub_record


class TruncatedTail(ValueError):
    """The final line of a JSONL file is incomplete (crash mid-write)."""


def append_json_lines(path: Path, objs: list[dict[str, Any]]) -> None:
    """Append one canonical JSON line per object under an exclusive flock."""
    payload = "".join(
        json.dumps(o, ensure_ascii=False, sort_keys=True) + "\n" for o in objs
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def read_json_lines(path: Path, *, tolerate_truncated_tail: bool = False) -> list[dict[str, Any]]:
    """Parse a JSONL file. A bad final line without newline is a truncated tail."""
    if not path.exists():
        return []
    lines = path.read_bytes().decode("utf-8").split("\n")
    complete = lines[-1] == ""  # file ends with a newline
    if complete:
        lines.pop()
    out: list[dict[str, Any]] = []
    for n, line in enumerate(lines, start=1):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            if n == len(lines) and not complete:
                if tolerate_truncated_tail:
                    break
                raise TruncatedTail(f"{path}: truncated final line {n}") from exc
            raise ValueError(f"{path}: corrupt line {n}: {exc}") from exc
    return out


class ProvStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, *records: Record) -> None:
        dicts = []
        for r in records:
            d = to_dict(scrub_record(r))
            assert_clean(d)
            dicts.append(d)
        append_json_lines(self.path, dicts)

    def read(self, *, tolerate_truncated_tail: bool = False) -> list[Record]:
        rows = read_json_lines(self.path, tolerate_truncated_tail=tolerate_truncated_tail)
        return [from_dict(d) for d in rows]

    def iter(self, *, tolerate_truncated_tail: bool = False) -> Iterator[Record]:
        yield from self.read(tolerate_truncated_tail=tolerate_truncated_tail)
