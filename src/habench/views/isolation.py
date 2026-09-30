"""Isolation of the method process (SPEC 11.2): an audit hook and a view leak scanner.

This module runs inside the method process, so it must not import habench.pipeline,
habench.oracle or habench.scenarios.
"""

from __future__ import annotations

import gzip
import io
import os
import sys
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

FORBIDDEN_MODULES = ("habench.pipeline", "habench.oracle", "habench.scenarios")

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
_DENIED_EVENTS = frozenset(
    {
        "subprocess.Popen",
        "_posixsubprocess.fork_exec",
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.spawn",
        "os.fork",
        "os.forkpty",
        "pty.spawn",
    }
)
_DENIED_EVENT_PREFIXES = ("socket.", "ctypes.")  # sockets and native-code bypass vectors
# Mutating filesystem events -> indices of the path arguments that must lie in scratch.
_MUTATING_EVENTS = {
    "os.remove": (0,),
    "os.rmdir": (0,),
    "os.mkdir": (0,),
    "os.truncate": (0,),
    "os.rename": (0, 1),
    "os.link": (0, 1),
    "os.symlink": (1,),
}
# Device files that ordinary libraries read (randomness, null sink).
_DEVICE_READS = (Path("/dev/null"), Path("/dev/urandom"), Path("/dev/random"))


@dataclass(frozen=True)
class Policy:
    view_root: Path  # the only data directory the method may read or list
    truth_root: Path  # always denied, even when under an allowed prefix
    read_prefixes: tuple[Path, ...]  # read-only code locations (interpreter, site-packages, repo src)
    scratch: Path | None = None  # optional writable directory
    # Source directories of FORBIDDEN_MODULES: denied to `open`, so they cannot be loaded by path
    # (importlib.util.spec_from_file_location) under another module name.
    denied_code: tuple[Path, ...] = ()


def _real(path: Path | str) -> Path:
    return Path(os.path.realpath(path))


def default_policy(view_root: Path, truth_root: Path, extra_read: Iterable[Path] = ()) -> Policy:
    """Build a policy whose read prefixes are the interpreter prefixes and the sys.path entries."""
    candidates = [sys.prefix, sys.base_prefix, sys.exec_prefix, *sys.path, *extra_read, *_DEVICE_READS]
    prefixes: list[Path] = []
    for entry in candidates:
        if str(entry) == "":  # '' means the working directory, which is not a code location
            continue
        real = _real(entry)
        if real not in prefixes:
            prefixes.append(real)
    denied = tuple(_real(p / "habench" / name.split(".")[1]) for p in prefixes for name in FORBIDDEN_MODULES)
    return Policy(_real(view_root), _real(truth_root), tuple(prefixes), denied_code=denied)


def _under(path: Path, roots: Iterable[Path | None]) -> bool:
    return any(root is not None and path.is_relative_to(root) for root in roots)


def _is_write(mode: object, flags: object) -> bool:
    if isinstance(mode, str) and any(c in mode for c in "wax+"):
        return True
    return isinstance(flags, int) and bool(flags & _WRITE_FLAGS)


def _is_forbidden_module(name: object) -> bool:
    return isinstance(name, str) and any(name == m or name.startswith(m + ".") for m in FORBIDDEN_MODULES)


class _Hook:
    def __init__(self, policy: Policy) -> None:
        self.p = policy
        self.code_roots = (policy.view_root, *policy.read_prefixes)

    def _check_read(self, path: Path, what: str) -> None:
        if _under(path, (self.p.truth_root, *self.p.denied_code)):
            raise PermissionError(f"isolation: {what} of a denied location: {path}")
        if not _under(path, self.code_roots):
            raise PermissionError(f"isolation: {what} outside the view: {path}")

    def _check_write(self, path: Path) -> None:
        if not _under(path, (self.p.scratch,)) or _under(path, (self.p.truth_root,)):
            raise PermissionError(f"isolation: write outside scratch: {path}")

    def __call__(self, event: str, args: tuple) -> None:
        if event == "open":
            path, mode, flags = args[0], args[1], args[2]
            # File descriptors and None are allowed: a descriptor was opened earlier, through this
            # hook or before install (the broker pipe), so its target was already decided.
            if path is None or isinstance(path, int):
                return
            real = _real(os.fsdecode(path))
            if _is_write(mode, flags):
                self._check_write(real)
            else:
                self._check_read(real, "read")
        elif event in ("os.listdir", "os.scandir"):
            target = args[0]
            if isinstance(target, int):  # directory descriptor, see the `open` rule
                return
            self._check_read(_real("." if target is None else os.fsdecode(target)), "listing")
        elif event == "glob.glob":
            pattern, root_dir = os.fsdecode(args[0]), args[2] if len(args) > 2 else None
            base = os.path.join(os.fsdecode(root_dir), pattern) if root_dir else pattern
            self._check_read(_real(_fixed_prefix(base) or "."), "glob")
        elif event == "import":
            if _is_forbidden_module(args[0]):
                raise PermissionError(f"isolation: import of {args[0]} is denied")
        elif event in _MUTATING_EVENTS:
            for i in _MUTATING_EVENTS[event]:
                if i < len(args) and isinstance(args[i], str | bytes | os.PathLike):
                    self._check_write(_real(os.fsdecode(args[i])))
        elif event in _DENIED_EVENTS or event.startswith(_DENIED_EVENT_PREFIXES):
            raise PermissionError(f"isolation: {event} is denied")


def _fixed_prefix(pattern: str) -> str:
    """Directory part of a glob pattern that precedes its first magic character."""
    cut = min((i for i in (pattern.find(c) for c in "*?[") if i >= 0), default=len(pattern))
    head = pattern[:cut]
    return head if cut == len(pattern) else os.path.dirname(head)


def install(policy: Policy) -> None:
    """Install the audit hook. Irreversible: audit hooks cannot be removed.

    Refuses when a forbidden module is already loaded: importing an already cached module does not
    fire the `import` audit event, so the hook could not deny it.
    """
    loaded = [m for m in sys.modules if _is_forbidden_module(m)]
    if loaded:
        raise RuntimeError(f"forbidden modules already imported: {sorted(loaded)}")
    hook = _Hook(replace(policy))
    sys.addaudithook(hook)


def scan_leaks(root: Path, terms: Iterable[str]) -> list[tuple[str, str]]:
    """Return (relative path, term) hits of case-insensitive terms in names and decompressed contents.

    Archive members are reported as "archive!member". The same pair is reported once.
    """
    needles = [t for t in terms if t]
    hits: list[tuple[str, str]] = []

    def check(label: str, name: str, data: bytes | None) -> None:
        low_name = name.lower()
        low_data = data.lower() if data is not None else b""
        for term in needles:
            if term.lower() in low_name or term.lower().encode() in low_data:
                if (label, term) not in hits:
                    hits.append((label, term))

    def scan_bytes(label: str, name: str, data: bytes, depth: int = 0) -> None:
        check(label, name, data)
        if depth >= 4:
            return
        if data[:2] == b"\x1f\x8b":
            try:
                inner = gzip.decompress(data)
            except (OSError, EOFError):
                return
            scan_bytes(label, name, inner, depth + 1)
        elif data[:4] == b"PK\x03\x04":
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    for info in zf.infolist():
                        member = f"{label}!{info.filename}"
                        check(member, info.filename, None)
                        if not info.is_dir():
                            scan_bytes(member, info.filename, zf.read(info), depth + 1)
            except zipfile.BadZipFile:
                return

    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        check(rel, rel, None)
        if path.is_file():
            scan_bytes(rel, rel, path.read_bytes())
    return hits
