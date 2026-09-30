"""Method-process side of the broker RPC (SPEC §11.2): child entry point and the `RpcEnv` proxy.

This module runs inside the isolated method process, so it must not import, directly or transitively,
`habench.pipeline`, `habench.oracle` or `habench.scenarios` (nor `env.broker`, `env.rpc`, `env.table`): it may import
only `habench.methods.base`, `habench.types` and `habench.views.isolation`. It has no import-time side effects, so a
spawned child can import it freely.

Wire protocol over the duplex pipe, everything plain data:
- child -> parent: `(op, args)` requests; `("done", payload)` or `("error", message)` as the last message.
- parent -> child: `("ok", value)` or `("err", kind, reason, message)`, `kind` in {"unavailable", "budget", "value",
  "broker"}.
"""

from __future__ import annotations

import importlib
import resource
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from habench.methods.base import (
    ArtifactRef,
    BudgetExhausted,
    Certificate,
    ContrastInfo,
    EvalResult,
    Explanation,
    Meter,
    PresenceMap,
    Query,
    TraceRecord,
    Unavailable,
    validated,
)
from habench.types import AssocKey, OutputState, Presence

# ---------------------------------------------------------------------- plain-data codecs


def encode_result(r: EvalResult) -> dict:
    presence = r.presence if isinstance(r.presence, PresenceMap) else PresenceMap(
        (k for k, v in r.presence.items() if v == Presence.PRESENT),
        {k.med for k, v in r.presence.items() if v == Presence.UNAVAILABLE},
    )
    trace = [
        [t.med, t.code, None if t.key is None else list(_key(t.key)), t.verdict, sorted(t.failed)] for t in r.trace
    ]
    return {"presence": presence.to_json(), "trace": trace}


def decode_result(o: Mapping[str, Any]) -> EvalResult:
    trace = tuple(
        TraceRecord(med, code, None if key is None else AssocKey(*key), verdict, frozenset(failed))
        for med, code, key, verdict, failed in o["trace"]
    )
    return EvalResult(PresenceMap.from_json(o["presence"]), trace)


def _key(k: AssocKey) -> tuple[int, str, str, str]:
    return (k.med, k.system, k.version, k.code)


def encode_explanation(e: Explanation) -> tuple:
    return (
        e.qid,
        e.state.value,
        tuple(tuple(tuple(s) for s in fam) for fam in e.families),
        tuple((c.kind, tuple(c.subject), c.value) for c in e.certificates),
        e.reason,
        e.confidence,
        tuple(e.notes),
    )


def decode_explanation(t: Sequence[Any]) -> Explanation:
    qid, state, families, certificates, reason, confidence, notes = t
    return Explanation(
        qid=qid,
        state=OutputState(state),
        families=tuple(tuple(tuple(s) for s in fam) for fam in families),
        certificates=tuple(Certificate(kind, tuple(subject), value) for kind, subject, value in certificates),
        reason=reason,
        confidence=confidence,
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------- the proxy Env


class RpcEnv:
    """The `Env` of the method process: every call is a request to the broker in the parent.

    Constant answers (contrast, artifacts, configs, finals, factors, capability) are fetched once."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self._memo: dict[tuple, Any] = {}

    def _call(self, op: str, *args: Any) -> Any:
        self._conn.send((op, args))
        reply = self._conn.recv()
        if reply[0] == "ok":
            return reply[1]
        _, kind, reason, message = reply
        if kind == "unavailable":
            raise Unavailable(reason, message)
        if kind == "budget":
            raise BudgetExhausted(message)
        if kind == "value":
            raise ValueError(message)
        raise RuntimeError(f"broker_error: {message}")

    def _once(self, op: str, *args: Any) -> Any:
        key = (op, *args)
        if key not in self._memo:
            self._memo[key] = self._call(op, *args)
        return self._memo[key]

    def contrast(self) -> ContrastInfo:
        cid, runs, space, budget = self._once("contrast")
        return ContrastInfo(cid, (runs[0], runs[1]), space, budget)

    def artifacts(self) -> Sequence[ArtifactRef]:
        return tuple(ArtifactRef(*a) for a in self._once("artifacts"))

    def read(self, ref: ArtifactRef) -> bytes:
        return self._call("read", (ref.ref, ref.kind, ref.run))

    def config(self, run: str) -> Mapping[str, str]:
        return dict(self._once("config", run))

    def executed_config(self, run: str) -> Mapping[str, str]:
        return dict(self._once("executed_config", run))

    def final(self, run: str) -> Mapping[AssocKey, Presence]:
        return PresenceMap.from_json(self._once("final", run))

    def factors(self) -> Sequence[str]:
        return tuple(self._once("factors"))

    def capability(self) -> str:
        return self._once("capability")

    def evaluate(self, apply: frozenset[str]) -> EvalResult:
        return decode_result(self._call("evaluate", sorted(apply)))

    def meter(self) -> Meter:
        evaluations, bytes_read, cpu, rss = self._call("meter")
        return Meter(evaluations, bytes_read, cpu, rss)


# ---------------------------------------------------------------------- child entry point


def child_main(
    conn: Any,
    method: str,
    view_dir: str,
    truth_root: str,
    extra_read: Sequence[str],
    queries: Sequence[tuple[str, tuple[int, str, str, str]]],
) -> None:
    """Target of the spawned process. Installs the audit hook first, then imports and runs the method.

    `method` is "module:Class". Sends `("done", payload)` with the explanations and this process's CPU seconds and
    peak RSS (bytes), or `("error", message)` for any exception."""
    try:
        sys.dont_write_bytecode = True  # the hook denies writes; never try to cache bytecode
        from habench.views.isolation import default_policy, install

        install(default_policy(Path(view_dir), Path(truth_root), [Path(p) for p in extra_read]))
        module_name, _, cls_name = method.partition(":")
        if not cls_name:
            raise ValueError(f"method spec must be 'module:Class', got {method!r}")
        instance = getattr(importlib.import_module(module_name), cls_name)()
        qs = [Query(qid, AssocKey(*key)) for qid, key in queries]
        out = instance.explain(RpcEnv(conn), qs)
        explanations = {qid: encode_explanation(validated(e)) for qid, e in out.items()}
        usage = resource.getrusage(resource.RUSAGE_SELF)
        payload = {
            "explanations": explanations,
            "cpu_seconds": usage.ru_utime + usage.ru_stime,
            "peak_rss": usage.ru_maxrss * 1024,  # KiB on Linux
        }
        conn.send(("done", payload))
    except BaseException as exc:  # noqa: BLE001 - any failure of the method becomes falha_de_execucao
        try:
            conn.send(("error", f"{type(exc).__name__}: {exc}"))
        except BaseException:  # noqa: BLE001 - the pipe is gone; the parent sees the exit code
            raise SystemExit(1) from None
