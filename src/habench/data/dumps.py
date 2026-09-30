"""Streaming reader for mysqldump .sql files (one INSERT line at a time, no MySQL needed).

Value semantics: NULL -> None; integer literal -> int; number literal with ``.``/``e``/``E`` -> float parsed
from the dump text; quoted string (optionally ``_binary``) -> str, unescaped like MySQL.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

DUMPS_DIR = Path(os.environ.get("HAB_DUMPS_DIR", "/home/vinicius/healdb-reconstrucao/x"))

SOURCES: dict[str, str] = {
    "V1": "v1_dump_0711/Dump20250711_Dump_and_Structure",
    "V2": "v2_dump_0828/DumpHealDBOpenSource_20260828",
    "G0327": "g0327_DumpHealDBOpenSource20250327/DumpHealDBOpenSource20250327",
    "O0605": "g0605_DumpHealDBOpenSource20250605/Dump20250605 (1)",
}

_VAL = re.compile(
    r"\s*(?:(NULL)|(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)|(?:_binary )?'((?:[^'\\]+|\\.|'')*)')\s*", re.S
)
_ESC = {"0": "\0", "n": "\n", "r": "\r", "t": "\t", "b": "\b", "Z": "\x1a"}
_UNESC = re.compile(r"\\(.)|''", re.S)
_FLOAT_MARK = re.compile(r"[.eE]")
_COLUMN = re.compile(r"\s+`([^`]+)` ")


def _unescape(s: str) -> str:
    if "\\" not in s and "''" not in s:
        return s
    return _UNESC.sub(lambda m: "'" if m.group(1) is None else _ESC.get(m.group(1), m.group(1)), s)


def path(label: str, table: str) -> Path:
    """Dump file of ``table`` in source ``label`` (a key of SOURCES or a directory relative to DUMPS_DIR)."""
    return DUMPS_DIR / SOURCES.get(label, label) / f"healdb_{table}.sql"


def create_table_lines(file: Path) -> list[str]:
    """Column definition lines of the CREATE TABLE statement, in order."""
    lines: list[str] = []
    inside = False
    with open(file, encoding="utf-8", errors="surrogateescape") as f:
        for line in f:
            if line.startswith("CREATE TABLE"):
                inside = True
            elif inside:
                if not _COLUMN.match(line):
                    break
                lines.append(line)
    return lines


def columns(label: str, table: str, file: Path | None = None) -> list[str]:
    """Column names in CREATE TABLE order."""
    return [_COLUMN.match(line).group(1) for line in create_table_lines(file or path(label, table))]  # type: ignore[union-attr]


def rows(label: str, table: str, file: Path | None = None) -> Iterator[list]:
    """Yield each row as a list of values (None, int, float or str)."""
    prefix = f"INSERT INTO `{table}` VALUES "
    match = _VAL.match
    with open(file or path(label, table), encoding="utf-8", errors="surrogateescape", newline="\n") as f:
        for line in f:
            if not line.startswith(prefix):
                continue
            i = len(prefix)
            try:
                while True:
                    if line[i] != "(":
                        raise ValueError(f'{table}: expected "(" at position {i}')
                    i += 1
                    row: list = []
                    while True:
                        m = match(line, i)
                        if not m:
                            raise ValueError(f"{table}: unreadable value at position {i}: {line[i:i + 40]!r}")
                        null, num, s = m.groups()
                        if s is not None:
                            row.append(_unescape(s))
                        elif num is not None:
                            row.append(float(num) if _FLOAT_MARK.search(num) else int(num))
                        else:
                            row.append(None)
                        i = m.end()
                        c, i = line[i], i + 1
                        if c == ")":
                            break
                        if c != ",":
                            raise ValueError(f"{table}: unexpected separator {c!r} at position {i - 1}")
                    yield row
                    c, i = line[i], i + 1
                    if c == ";":
                        break
                    if c != ",":
                        raise ValueError(f"{table}: unexpected separator {c!r} between rows")
            except IndexError:
                raise ValueError(f"{table}: truncated INSERT statement") from None


def records(label: str, table: str, file: Path | None = None) -> Iterator[dict]:
    """Like rows(), but each row is a dict column -> value."""
    cols = columns(label, table, file)
    for r in rows(label, table, file):
        yield dict(zip(cols, r))
