"""Parent side of the broker RPC (SPEC §11.2): run a method in an isolated child process against a `BrokerEnv`.

The child is spawned (never forked), gets a duplex Pipe created before it installs the audit hook, and serves
every `Env` call through the parent. Any child exception, crash, non-zero exit or timeout turns every query into
`falha_de_execucao` with reason `method_error: ...`; a failed execution is never read as absence (CLAUDE.md).

The timeout is checked between requests: a single broker evaluation in the parent is not interrupted.
"""

from __future__ import annotations

import multiprocessing
import sys
import time
import types
from collections.abc import Sequence
from dataclasses import dataclass
from multiprocessing.connection import wait
from pathlib import Path
from typing import Any

from habench.env.broker import BrokerEnv
from habench.env.child import child_main, decode_explanation, encode_result
from habench.methods.base import ArtifactRef, BudgetExhausted, Explanation, Meter, Query, Unavailable, validated
from habench.types import OutputState

KILL_GRACE = 10.0  # seconds to let a finished child exit before it is killed


@dataclass(frozen=True)
class RunOutcome:
    explanations: dict[str, Explanation]
    meter: Meter  # broker evaluations and bytes; cpu = broker + child; peak RSS = child's
    child_cpu_seconds: float = 0.0
    error: str | None = None


def run_isolated(
    method: str,
    env: BrokerEnv,
    queries: Sequence[Query],
    *,
    view_dir: Path,
    truth_root: Path,
    extra_read: Sequence[Path] = (),
    timeout: float = 600,
) -> RunOutcome:
    """Run `method` ("module:Class") on `queries` in a child process whose only channel to the truth side is `env`."""
    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=True)
    plain_queries = [(q.qid, (q.key.med, q.key.system, q.key.version, q.key.code)) for q in queries]
    proc = ctx.Process(
        target=child_main,
        args=(child_conn, method, str(view_dir), str(truth_root), [str(p) for p in extra_read], plain_queries),
        daemon=True,
    )
    # Spawn re-imports the parent's __main__ in the child (by name or by path). A trusted entry point such as
    # `python -m habench.runner...` would pull oracle/pipeline into the child before the hook is installed, so the
    # child is started with a bare __main__ (no __spec__, no __file__: nothing to re-import).
    real_main = sys.modules.get("__main__")
    sys.modules["__main__"] = types.ModuleType("__main__")
    try:
        proc.start()
    finally:
        if real_main is not None:
            sys.modules["__main__"] = real_main
        else:
            sys.modules.pop("__main__", None)
    child_conn.close()

    payload: dict[str, Any] | None = None
    error: str | None = None
    deadline = time.monotonic() + timeout
    try:
        while payload is None and error is None:
            remaining = deadline - time.monotonic()
            ready = wait([parent_conn, proc.sentinel], timeout=max(remaining, 0)) if remaining > 0 else []
            if not ready:
                error = f"timeout after {timeout}s"
                break
            if parent_conn not in ready and not parent_conn.poll(0):
                proc.join(1)
                error = f"child exited with code {proc.exitcode} without a result"
                break
            try:
                msg = parent_conn.recv()
            except (EOFError, OSError):
                proc.join(1)
                error = f"child exited with code {proc.exitcode} without a result"
                break
            if msg[0] == "done":
                payload = msg[1]
            elif msg[0] == "error":
                error = msg[1]
            else:
                _serve(env, parent_conn, msg)
    finally:
        _reap(proc, parent_conn, kill=payload is None)
    if payload is not None and proc.exitcode != 0:
        error, payload = f"child exited with code {proc.exitcode}", None

    base = env.meter()
    if payload is None or error is not None:
        reason = f"method_error: {error}"
        failed = {q.qid: Explanation(q.qid, OutputState.FALHA_DE_EXECUCAO, reason=reason) for q in queries}
        return RunOutcome(failed, base, 0.0, error)

    explanations: dict[str, Explanation] = {}
    for q in queries:
        raw = payload["explanations"].get(q.qid)
        if raw is None:
            explanations[q.qid] = Explanation(
                q.qid, OutputState.FALHA_DE_EXECUCAO, reason="method_error: no explanation returned for the query"
            )
        else:
            explanations[q.qid] = validated(decode_explanation(raw))
    meter = Meter(base.evaluations, base.bytes_read, base.cpu_seconds + payload["cpu_seconds"], payload["peak_rss"])
    return RunOutcome(explanations, meter, payload["cpu_seconds"], None)


def _reap(proc: Any, conn: Any, *, kill: bool) -> None:
    if kill and proc.is_alive():
        proc.kill()
    proc.join(KILL_GRACE)
    if proc.is_alive():
        proc.kill()
        proc.join()
    conn.close()


def _serve(env: BrokerEnv, conn: Any, msg: Sequence[Any]) -> None:
    """Answer one request of the child from the broker."""
    try:
        reply: tuple = ("ok", _dispatch(env, msg[0], msg[1]))
    except Unavailable as exc:
        reply = ("err", "unavailable", exc.reason, str(exc))
    except BudgetExhausted as exc:
        reply = ("err", "budget", "", str(exc))
    except ValueError as exc:
        reply = ("err", "value", "", str(exc))
    except Exception as exc:  # noqa: BLE001 - a broker defect must not hang the child
        reply = ("err", "broker", "", f"{type(exc).__name__}: {exc}")
    conn.send(reply)


def _dispatch(env: BrokerEnv, op: str, args: Sequence[Any]) -> Any:
    if op == "contrast":
        c = env.contrast()
        return (c.cid, c.runs, c.space, c.budget)
    if op == "artifacts":
        return [(a.ref, a.kind, a.run) for a in env.artifacts()]
    if op == "read":
        return env.read(ArtifactRef(*args[0]))
    if op in ("config", "executed_config"):
        return dict(getattr(env, op)(args[0]))
    if op == "final":
        return env.final(args[0]).to_json()  # type: ignore[union-attr]
    if op == "factors":
        return list(env.factors())
    if op == "capability":
        return env.capability()
    if op == "evaluate":
        return encode_result(env.evaluate(frozenset(args[0])))
    if op == "meter":
        m = env.meter()
        return (m.evaluations, m.bytes_read, m.cpu_seconds, m.peak_rss)
    raise ValueError(f"unknown op {op!r}")
