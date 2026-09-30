"""Executes a campaign schedule: one reservation and one provenance record per attempt, resumable, capped.

Layout of a run directory (<HAB_DATA_DIR>/campaign/<run_id>/):
  run.json            run manifest (schedule and plan hashes, agent id)
  prov.jsonl          PROV records: one activity per attempt, block starts, skipped calls
  raw/<attempt>.body  exact HTTP body; raw/<attempt>.json the parsed response as HealDB stored it
  inputs/<attempt>.txt  effective ACM text of full-pipeline attempts
  outputs/<attempt>.txt translation output text

Without backends the run is dry: reservations go to an in-memory copy of the ledger, nothing is written, nothing waits.
"""

import fcntl
import hashlib
import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from habench.campaign.acm import AcmOutcome
from habench.campaign.calls import (
    ACM_TEXT_LIMIT,
    Condition,
    Schedule,
    ScheduledCall,
    Service,
    acm_cost_usd,
    acm_units,
    acm_worst_case_usd,
    pipeline_acm_text,
    sha256_text,
    translate_cost_usd,
    translate_worst_case_usd,
    translation_prompt,
)
from habench.campaign.money import CapExceeded, Ledger
from habench.campaign.plan import Plan, PlanError, Profile
from habench.campaign.translate import TranslationOutcome
from habench.prov.records import Activity, Agent, Entity, Relation, RelationKind, new_id, utc_now
from habench.prov.scrub import SecretLeak, assert_clean_bytes
from habench.prov.store import ProvStore

KIND_ACM = "acm.infer_icd10_cm"
KIND_TRANSLATE = "bedrock.converse"
KIND_BLOCK = "campaign.block_start"
KIND_SKIP = "campaign.call_not_executed"
KIND_ORPHAN = "campaign.attempt_interrupted"


@dataclass(frozen=True, slots=True)
class Backends:
    """acm(text) and translate(profile, prompt, max_tokens); real ones come from campaign.cli.real_backends."""

    acm: Callable[[str], AcmOutcome]
    translate: Callable[[Profile, str, int], TranslationOutcome]


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    status: str  # completed | cap_reached | dry_run
    n_calls: int
    n_ok: int
    n_failed: int
    n_not_executed: int
    n_planned: int  # dry run: calls that fit the cap and budget
    n_attempts: int
    run_spent_usd: float
    stop_reason: str | None


class RunError(RuntimeError):
    pass


def _versions() -> dict[str, str]:
    out = {}
    for pkg in ("habench", "boto3", "botocore"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = "absent"
    return out


def worst_case_usd(call: ScheduledCall, plan: Plan, text: str | None) -> float:
    """Worst case of one attempt. text is the effective input (None: full-pipeline text not known yet)."""
    if call.service is Service.ACM:
        return acm_worst_case_usd(ACM_TEXT_LIMIT, plan.acm_price) if text is None else acm_cost_usd(text,
                                                                                                    plan.acm_price)
    assert call.profile is not None and text is not None
    model = plan.profile(call.profile).model_id
    if plan.missing_prices({model}):
        raise PlanError(f"no price for model {model!r}: fill token_prices (see `estimate`)")
    return translate_worst_case_usd(translation_prompt(text), plan.max_tokens, plan.token_prices[model])


@dataclass
class _CallState:
    status: str | None = None  # ok | failed | not_executed (terminal) or None
    last_activity: str | None = None
    output_entity: str | None = None
    output_text: str | None = None


class Runner:
    def __init__(self, schedule: Schedule, plan: Plan, *, run_dir: Path, run_id: str, ledger: Ledger,
                 backends: Backends | None, budget_usd: float, code_ref: dict[str, Any] | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.time) -> None:
        self.schedule, self.plan = schedule, plan
        self.run_dir, self.run_id = run_dir, run_id
        self.dry = backends is None
        self.ledger = ledger.dry_copy() if self.dry else ledger
        self.backends = backends
        self.budget_usd = budget_usd
        self.code = {"package": "habench", "module": __name__, **(code_ref or {})}
        self.sleep, self.clock = sleep, clock
        self.store = None if self.dry else ProvStore(run_dir / "prov.jsonl")

    # ---------------------------------------------------------------- state

    def _schedule_sha(self) -> str:
        return hashlib.sha256(self.schedule.to_json().encode("utf-8")).hexdigest()

    def _open_run(self) -> str:
        """Create or verify run.json; return the agent id."""
        manifest = self.run_dir / "run.json"
        if manifest.exists():
            m = json.loads(manifest.read_text(encoding="utf-8"))
            if m["schedule_sha256"] != self._schedule_sha() or m["run_id"] != self.run_id:
                raise RunError(f"{manifest} belongs to another schedule or run id")
            return m["agent_id"]
        agent_id = new_id()
        m = {"run_id": self.run_id, "schedule_sha256": self._schedule_sha(), "kind": self.schedule.kind,
             "plan_sha256": self.schedule.plan_sha256, "manifest_sha256": self.schedule.manifest_sha256,
             "created": utc_now(), "agent_id": agent_id, "region": self.plan.region}
        self.run_dir.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(m, indent=1, sort_keys=True), encoding="utf-8")
        assert self.store is not None
        self.store.append(Agent(id=agent_id, kind="software", attrs={"name": "habench.campaign.runner",
                                                                      "versions": _versions(), **self.code}))
        return agent_id

    def _load_states(self) -> tuple[dict[str, _CallState], dict[int, float]]:
        states = {c.call_id: _CallState() for c in self.schedule.calls}
        block_starts: dict[int, float] = {}
        if self.store is None:
            return states, block_starts
        outputs: dict[str, str] = {}  # activity id -> output entity id
        for r in self.store.read():
            if isinstance(r, Relation) and r.kind is RelationKind.WAS_GENERATED_BY:
                outputs[r.object] = r.subject
        for r in self.store.read():
            if not isinstance(r, Activity):
                continue
            if r.kind == KIND_BLOCK:
                block_starts[int(r.attrs["block"])] = float(r.attrs["epoch"])
                continue
            call_id = r.attrs.get("call_id")
            if call_id not in states or r.kind == KIND_ORPHAN:
                continue
            st = states[call_id]
            st.last_activity = r.id
            st.status = r.attrs.get("terminal")
            if r.status == "ok":
                st.output_entity = outputs.get(r.id)
                text_file = self.run_dir / "outputs" / f"{_fname(r.id)}.txt"
                if r.kind == KIND_TRANSLATE and text_file.exists():  # absent when refused by the secret check
                    st.output_text = text_file.read_text(encoding="utf-8")
        return states, block_starts

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        if self.dry:
            yield
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with open(self.run_dir / ".lock", "w") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RunError(f"run {self.run_id} is already being executed") from None
            yield

    # ---------------------------------------------------------------- run

    def run(self) -> RunResult:
        with self._exclusive():
            return self._run()

    def _run(self) -> RunResult:
        agent_id = "" if self.dry else self._open_run()
        if not self.dry:
            self._record_orphans()
        states, block_starts = self._load_states()
        calls = sorted(self.schedule.calls, key=lambda c: c.order)
        stop: str | None = None
        for call in calls:
            st = states[call.call_id]
            if st.status is not None:
                continue
            if not self.dry:
                self._wait_for_block(call.block, block_starts)
            parent = states[call.parent] if call.parent else None
            if parent is not None and not self.dry and (parent.status != "ok" or parent.output_text is None):
                reason = (f"parent {call.parent} status {parent.status}" if parent.status != "ok"
                          else f"parent {call.parent} output text was not stored")
                self._record_not_executed(call, agent_id, reason)
                st.status = "not_executed"
                continue
            if not self.dry and self._attempts_so_far(call.call_id) >= self.plan.retry.max_attempts:
                # e.g. the last allowed attempt was interrupted: attempts are never granted beyond the policy
                self._record_not_executed(call, agent_id, "attempts exhausted", terminal="failed")
                st.status = "failed"
                continue
            try:
                self._execute(call, st, parent, agent_id)
            except CapExceeded as exc:
                stop = str(exc)
                break
        return self._result(states, stop)

    def _wait_for_block(self, block: int, starts: dict[int, float]) -> None:
        if block in starts:
            return
        previous = [b for b in starts if b < block]
        if previous:
            due = starts[max(previous)] + self.plan.block_spacing_s
            wait = due - self.clock()
            if wait > 0:
                self.sleep(wait)
        now = self.clock()
        starts[block] = now
        assert self.store is not None
        self.store.append(Activity(id=new_id(), kind=KIND_BLOCK, status="ok", started=utc_now(), ended=None,
                                   attrs={"block": block, "epoch": now, "run_id": self.run_id}))

    def _record_orphans(self) -> None:
        """Reservations left by an interrupted process: recorded, reconciled at worst case, count as attempts."""
        assert self.store is not None
        recorded = {r.id for r in self.store.read() if isinstance(r, Activity)}
        for e in self.ledger.outstanding(self.run_id):
            self.ledger.reconcile(attempt_id=e["attempt_id"], usd=float(e["usd"]), basis="worst_case_orphan")
            if e["attempt_id"] in recorded:  # crashed between recording and reconciling
                continue
            self.store.append(Activity(id=e["attempt_id"], kind=KIND_ORPHAN, status="interrupted", started=e["ts"],
                                       ended=None, consumption={"usd_reserved": e["usd"], "usd_actual": e["usd"],
                                                                "cost_basis": "worst_case_orphan"},
                                       attrs={"call_id": e["meta"].get("call_id"), "run_id": self.run_id}))

    def _attempts_so_far(self, call_id: str) -> int:
        return sum(1 for e in self.ledger.entries()
                   if e["type"] == "reserve" and e["run_id"] == self.run_id and e["meta"].get("call_id") == call_id)

    def _record_not_executed(self, call: ScheduledCall, agent_id: str, reason: str,
                             terminal: str = "not_executed") -> None:
        assert self.store is not None
        aid = new_id()
        self.store.append(
            Activity(id=aid, kind=KIND_SKIP, status="not_executed", started=utc_now(), ended=None,
                     attrs={**_call_attrs(call, self.run_id), "terminal": terminal, "reason": reason}),
            Relation(RelationKind.WAS_ASSOCIATED_WITH, aid, agent_id))

    def _execute(self, call: ScheduledCall, st: _CallState, parent: _CallState | None, agent_id: str) -> None:
        if call.condition is Condition.FULL_PIPELINE:
            text = None if self.dry else pipeline_acm_text(parent.output_text or "")  # type: ignore[union-attr]
        else:
            text = call.input_text
        worst = worst_case_usd(call, self.plan, text)
        previous_activity: str | None = None
        attempt_no = self._attempts_so_far(call.call_id)
        while True:
            attempt_no += 1
            attempt_id = new_id()
            self.ledger.reserve(attempt_id=attempt_id, run_id=self.run_id, usd=worst, cap_usd=self.plan.cap_usd,
                                run_budget_usd=self.budget_usd,
                                meta={"call_id": call.call_id, "attempt": attempt_no, "service": str(call.service)})
            if self.dry:
                self.ledger.reconcile(attempt_id=attempt_id, usd=worst, basis="dry_run")
                st.status = "planned"
                return
            retryable = self._attempt(call, st, parent, agent_id, attempt_id, attempt_no, text, worst,
                                      previous_activity)
            previous_activity = attempt_id
            if st.status is not None:
                return
            assert retryable
            self.sleep(self.plan.retry.backoff_s * attempt_no)

    def _attempt(self, call: ScheduledCall, st: _CallState, parent: _CallState | None, agent_id: str,
                 attempt_id: str, attempt_no: int, text: str | None, worst: float,
                 previous_activity: str | None) -> bool:
        assert self.backends is not None and self.store is not None and text is not None
        records: list[Any] = []
        in_id = new_id()
        if call.service is Service.ACM:
            outcome: AcmOutcome | TranslationOutcome = self.backends.acm(text)
            kind, in_kind, out_kind = KIND_ACM, "acm_text", "acm_response"
            model_returned = outcome.model_version  # type: ignore[union-attr]
            config: dict[str, Any] = {"operation": "InferICD10CM", "parameters": ["Text"]}
            consumption: dict[str, Any] = {"input_chars": len(text), "units": acm_units(text, self.plan.acm_price)}
            if outcome.ok:
                actual, basis = acm_cost_usd(text, self.plan.acm_price), "price_list_units"
            else:
                actual, basis = worst, "worst_case_failed"
        else:
            profile = self.plan.profile(call.profile or "")
            prompt = translation_prompt(text)
            outcome = self.backends.translate(profile, prompt, self.plan.max_tokens)
            kind, in_kind, out_kind = KIND_TRANSLATE, "translation_prompt", "translation_response"
            model_returned = outcome.model_id  # type: ignore[union-attr]
            config = {"operation": "Converse", "model_id": profile.model_id, "temperature": profile.temperature,
                      "max_tokens": self.plan.max_tokens, "profile": profile.name}
            it, ot = outcome.input_tokens, outcome.output_tokens  # type: ignore[union-attr]
            consumption = {"prompt_bytes": len(prompt.encode("utf-8")), "input_tokens": it, "output_tokens": ot,
                           "stop_reason": outcome.stop_reason,  # type: ignore[union-attr]
                           "service_latency_ms": outcome.service_latency_ms}  # type: ignore[union-attr]
            if outcome.ok and it is not None and ot is not None:
                actual = translate_cost_usd(it, ot, self.plan.token_prices[profile.model_id])
                basis = "measured_tokens"
            else:
                actual, basis = worst, "worst_case_failed" if not outcome.ok else "worst_case_no_usage"
        consumption.update({"latency_ms": outcome.latency_ms, "usd_reserved": worst, "usd_actual": actual,
                            "cost_basis": basis})

        retryable = (not outcome.ok and outcome.error_code in self.plan.retry.retryable
                     and attempt_no < self.plan.retry.max_attempts)
        terminal = "ok" if outcome.ok else (None if retryable else "failed")
        error = None if outcome.ok else {"type": outcome.error_type, "code": outcome.error_code,
                                         "message": outcome.error_message, "retryable": retryable}

        # effective input
        in_attrs: dict[str, Any] = {"chars": len(text)}
        if call.condition is Condition.FULL_PIPELINE:
            self._write_checked(f"inputs/{_fname(attempt_id)}.txt", text.encode("utf-8"), in_attrs, "file")
        else:
            in_attrs["schedule_input_sha256"] = call.input_sha256
        input_sha = sha256_text(text if call.service is Service.ACM else translation_prompt(text))
        records.append(Entity(id=in_id, kind=in_kind, sha256=input_sha, attrs=in_attrs))
        records.append(Relation(RelationKind.USED, attempt_id, in_id))
        if call.condition is Condition.FULL_PIPELINE and parent is not None and parent.output_entity:
            records.append(Relation(RelationKind.WAS_DERIVED_FROM, in_id, parent.output_entity))

        # output (raw bytes exactly; also on failures, when the service returned a body)
        out_id = None
        text_refused = False
        raw = outcome.raw_body
        if raw is not None or outcome.response is not None:
            out_id = new_id()
            out_attrs: dict[str, Any] = {}
            if raw is not None:
                self._write_checked(f"raw/{_fname(attempt_id)}.body", raw, out_attrs, "body_file")
            if outcome.response is not None:
                js = json.dumps(outcome.response, ensure_ascii=False, default=str).encode("utf-8")
                self._write_checked(f"raw/{_fname(attempt_id)}.json", js, out_attrs, "json_file")
            if isinstance(outcome, TranslationOutcome) and outcome.output_text is not None:
                stored = self._write_checked(f"outputs/{_fname(attempt_id)}.txt",
                                             outcome.output_text.encode("utf-8"), out_attrs, "text_file")
                if not stored:
                    text_refused = True
            sha = hashlib.sha256(raw).hexdigest() if raw is not None else None
            records.append(Entity(id=out_id, kind=out_kind, sha256=sha, attrs=out_attrs))
            records.append(Relation(RelationKind.WAS_GENERATED_BY, out_id, attempt_id))

        records.insert(0, Activity(
            id=attempt_id, kind=kind, status="ok" if outcome.ok else "error", started=outcome.started,
            ended=outcome.ended, endpoint=outcome.endpoint, region=outcome.region, model_returned=model_returned,
            config=config, code=self.code, error=error, consumption=consumption, dependencies=_versions(),
            attrs={**_call_attrs(call, self.run_id), "attempt": attempt_no, "terminal": terminal,
                   "request_id": outcome.request_id, "http_date": outcome.http_date,
                   "http_status": outcome.http_status}))
        records.append(Relation(RelationKind.WAS_ASSOCIATED_WITH, attempt_id, agent_id))
        if previous_activity is not None:
            records.append(Relation(RelationKind.WAS_INFORMED_BY, attempt_id, previous_activity,
                                    attrs={"reason": "retry"}))
        if parent is not None and parent.last_activity is not None:
            records.append(Relation(RelationKind.WAS_INFORMED_BY, attempt_id, parent.last_activity,
                                    attrs={"reason": "pipeline_input"}))
        # record first: a crash before reconciling leaves an orphan reservation, counted at worst case
        self.store.append(*records)
        self.ledger.reconcile(attempt_id=attempt_id, usd=actual, basis=basis)

        st.last_activity = attempt_id
        st.status = terminal
        if outcome.ok:
            st.output_entity = out_id
            if isinstance(outcome, TranslationOutcome):
                st.output_text = None if text_refused else outcome.output_text
        return retryable

    def _write_checked(self, rel: str, data: bytes, attrs: dict[str, Any], key: str) -> bool:
        """Write data verbatim unless it matches a credential pattern; record the refusal instead."""
        try:
            assert_clean_bytes(data)
        except SecretLeak as exc:
            attrs[f"{key.removesuffix('_file')}_refused"] = str(exc)  # body_refused, json_refused, ...
            return False
        attrs[key] = self._write(rel, data)
        return True

    def _write(self, rel: str, data: bytes) -> str:
        path = self.run_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise RunError(f"refusing to overwrite {path}")
        path.write_bytes(data)
        return rel

    def _result(self, states: dict[str, _CallState], stop: str | None) -> RunResult:
        counts = {s: sum(1 for st in states.values() if st.status == s)
                  for s in ("ok", "failed", "not_executed", "planned")}
        status = "dry_run" if self.dry else ("cap_reached" if stop else "completed")
        return RunResult(run_id=self.run_id, status=status, n_calls=len(states), n_ok=counts["ok"],
                         n_failed=counts["failed"], n_not_executed=counts["not_executed"],
                         n_planned=counts["planned"],
                         n_attempts=sum(1 for e in self.ledger.entries()
                                        if e["type"] == "reserve" and e["run_id"] == self.run_id),
                         run_spent_usd=self.ledger.totals().run_spent_usd.get(self.run_id, 0.0),
                         stop_reason=stop)


def _fname(record_id: str) -> str:
    return record_id.removeprefix("urn:uuid:")


def _call_attrs(call: ScheduledCall, run_id: str) -> dict[str, Any]:
    return {"run_id": run_id, "call_id": call.call_id, "condition": str(call.condition), "role": str(call.role),
            "block": call.block, "order": call.order, "group_id": call.group_id, "medication": call.medication,
            "repetition": call.repetition, "profile": call.profile, "parent": call.parent}
