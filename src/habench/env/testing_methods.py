"""TEST FIXTURES ONLY: deliberately misbehaving methods for `tests/test_env_rpc.py`.

They live in an importable module because the spawned method process must be able to import them by name
("habench.env.testing_methods:ImportOracle"). This module runs inside the isolated child, so it imports only
`habench.methods.base` and `habench.types`. Nothing here is a real method and no runner may use it.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Mapping, Sequence

from habench.methods.base import (
    BudgetExhausted,
    Env,
    Explanation,
    Query,
    Unavailable,
    abstain,
)
from habench.types import OutputState

FORBIDDEN = ("habench.pipeline", "habench.oracle", "habench.scenarios")
CANARY_ENV = "HAB_TEST_CANARY"  # path of a canary file under the fake truth directory


def _all(queries: Sequence[Query], *notes: str) -> Mapping[str, Explanation]:
    return {q.qid: abstain(q.qid, OutputState.INFORMACAO_INSUFICIENTE, "report", *notes) for q in queries}


class ImportOracle:
    """Tries to import the oracle: the audit hook must deny it."""

    name = "test_import_oracle"

    def explain(self, env: Env, queries: Sequence[Query]) -> Mapping[str, Explanation]:
        import habench.oracle  # noqa: F401

        return _all(queries, "imported")


class OpenCanary:
    """Opens the canary file in the truth directory: the audit hook must deny it."""

    name = "test_open_canary"

    def explain(self, env: Env, queries: Sequence[Query]) -> Mapping[str, Explanation]:
        with open(os.environ[CANARY_ENV], encoding="utf-8") as f:
            return _all(queries, "read:" + f.read())


class Sleeper:
    name = "test_sleeper"

    def explain(self, env: Env, queries: Sequence[Query]) -> Mapping[str, Explanation]:
        time.sleep(600)
        return _all(queries)


class Crash:
    """Kills the process without a message."""

    name = "test_crash"

    def explain(self, env: Env, queries: Sequence[Query]) -> Mapping[str, Explanation]:
        os._exit(3)


class Forgetful:
    """Answers only the first query."""

    name = "test_forgetful"

    def explain(self, env: Env, queries: Sequence[Query]) -> Mapping[str, Explanation]:
        return _all(queries[:1])


class Invalid:
    """Returns a schema-violating explanation (a family on an abstention is fine; an empty set is not)."""

    name = "test_invalid"

    def explain(self, env: Env, queries: Sequence[Query]) -> Mapping[str, Explanation]:
        return {
            q.qid: Explanation(q.qid, OutputState.EXPLICACAO_VERIFICADA, families=(((),),)) for q in queries
        }


class Report:
    """Reports the forbidden and trusted modules loaded in this process."""

    name = "test_report"

    def explain(self, env: Env, queries: Sequence[Query]) -> Mapping[str, Explanation]:
        forbidden = sorted(m for m in sys.modules if any(m == f or m.startswith(f + ".") for f in FORBIDDEN))
        trusted = sorted(m for m in ("habench.env.broker", "habench.env.rpc", "habench.env.table") if m in sys.modules)
        return _all(queries, "forbidden=" + ",".join(forbidden), "trusted=" + ",".join(trusted),
                    "main_file=" + str(getattr(sys.modules.get("__main__"), "__file__", None)))


class Probe:
    """Exercises the error marshalling of the Env and reports what each call raised."""

    name = "test_probe"

    def explain(self, env: Env, queries: Sequence[Query]) -> Mapping[str, Explanation]:
        seen: list[str] = []

        def attempt(label: str, call) -> None:
            try:
                call()
                seen.append(f"{label}=ok")
            except Unavailable as exc:
                seen.append(f"{label}=Unavailable:{exc.reason}")
            except BudgetExhausted:
                seen.append(f"{label}=BudgetExhausted")
            except ValueError:
                seen.append(f"{label}=ValueError")

        attempt("unknown", lambda: env.evaluate(frozenset({"nope"})))
        attempt("empty", lambda: env.evaluate(frozenset()))
        attempt("full", lambda: env.evaluate(frozenset(env.factors())))
        attempt("executed_config", lambda: env.executed_config("x0"))
        attempt("bad_run", lambda: env.config("x9"))
        arts = env.artifacts()
        seen.append(f"artifacts={len(arts)}")
        seen.append(f"bytes={sum(len(env.read(a)) for a in arts)}")
        seen.append(f"capability={env.capability()}")
        seen.append(f"factors={','.join(env.factors())}")
        return _all(queries, *seen)
