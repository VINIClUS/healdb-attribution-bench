"""Command line of the Study C campaign: ``python -m habench.campaign {plan-smoke,plan-pilot,estimate,run,status,compare}``.

Runs are dry unless env HAB_PAID_CALLS=1, --paid and --budget-usd are all given and every model has a price.
boto3 is imported only by ``real_backends`` (through campaign.aws), never on a dry run.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from habench.campaign import acm as acm_adapter
from habench.campaign import aws, compare, money
from habench.campaign import translate as translate_adapter
from habench.campaign.calls import Condition, Schedule, Service
from habench.campaign.estimator import estimate, format_estimate
from habench.campaign.money import Ledger, PaidAuthorization, PaidCallRefused
from habench.campaign.plan import Plan, PlanError, plan_from_dict
from habench.campaign.runner import KIND_ACM, KIND_ORPHAN, KIND_TRANSLATE, Backends, RunError, Runner
from habench.campaign.schedule import plan_pilot, plan_smoke, read_manifest
from habench.campaign.texts import ParquetTextSource
from habench.prov.records import Activity, Entity, Relation, RelationKind
from habench.prov.store import ProvStore
from habench.types import SealedError

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = "/home/vinicius/hab-data"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
TERMINAL_STATES = ("ok", "failed", "not_executed")
EXIT_USAGE = 2
EXIT_REFUSED = 3


class CliError(Exception):
    """A user-facing failure; main prints it and exits with EXIT_USAGE."""


@dataclass(frozen=True, slots=True)
class Paths:
    data_dir: Path
    ledger: Path
    campaign_dir: Path


# ---------------------------------------------------------------- helpers


def _run_id(value: str) -> str:
    if not RUN_ID_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(f"run id {value!r} must match {RUN_ID_RE.pattern}")
    return value


def _resolve_paths(args: argparse.Namespace, env: Mapping[str, str]) -> Paths:
    data_dir = Path(args.data_dir or env.get("HAB_DATA_DIR") or DEFAULT_DATA_DIR)
    campaign_dir = Path(args.campaign_dir) if args.campaign_dir else data_dir / "campaign"
    ledger = Path(args.ledger) if args.ledger else data_dir / "campaign" / "ledger.jsonl"
    return Paths(data_dir=data_dir, ledger=ledger, campaign_dir=campaign_dir)


def _load_plan(path: Path) -> tuple[Plan, str]:
    raw = path.read_bytes()
    return plan_from_dict(yaml.safe_load(raw)), hashlib.sha256(raw).hexdigest()


def _load_matching(plan_path: Path, schedule_path: Path) -> tuple[Plan, Schedule]:
    plan, plan_sha = _load_plan(plan_path)
    schedule = Schedule.load(schedule_path)
    if schedule.plan_sha256 != plan_sha:
        raise CliError(f"plan hash mismatch: schedule has {schedule.plan_sha256}, plan file is {plan_sha}")
    return plan, schedule


def _open_ledger(path: Path) -> Ledger:
    """Read-only use: a missing ledger file is an empty in-memory ledger (nothing is created)."""
    return Ledger(path if path.exists() else None)


def _dump(obj: Any) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True)


def git_code_ref() -> dict[str, Any] | None:
    """Commit and dirtiness of the repository, or None when git is unavailable."""
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
        status = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True,
                                check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return {"git_commit": head, "git_dirty": bool(status.strip())}


def real_backends(auth: PaidAuthorization, plan: Plan) -> Backends:
    """Real AWS backends; the only place that builds clients. Requires a PaidAuthorization."""
    acm_client, bedrock_client = aws.real_clients(auth, plan.region)
    return Backends(
        acm=lambda text: acm_adapter.infer_icd10_cm(acm_client, text),
        translate=lambda profile, prompt, max_tokens: translate_adapter.converse_translate(
            bedrock_client, model_id=profile.model_id, prompt=prompt, max_tokens=max_tokens,
            temperature=profile.temperature))


# ---------------------------------------------------------------- plan / estimate


def _cmd_plan(args: argparse.Namespace, paths: Paths, env: Mapping[str, str]) -> int:
    plan, plan_sha = _load_plan(Path(args.plan))
    manifest = Path(args.manifest) if args.manifest else REPO_ROOT / "repro" / "split_manifest.csv"
    snapshots = Path(args.snapshots) if args.snapshots else paths.data_dir / "snapshots"
    rows, manifest_sha = read_manifest(manifest)
    planner = plan_smoke if args.command == "plan-smoke" else plan_pilot
    schedule = planner(rows, manifest_sha, plan, plan_sha, ParquetTextSource(snapshots))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    schedule.save(out)
    by_condition = Counter(str(c.condition) for c in schedule.calls)
    print(f"schedule {schedule.kind}: {len(schedule.calls)} calls written to {out}")
    for condition, n in sorted(by_condition.items()):
        print(f"  {condition}: {n}")
    print(f"excluded medications: {len(schedule.excluded)}")
    return 0


def _cmd_estimate(args: argparse.Namespace, paths: Paths, env: Mapping[str, str]) -> int:
    plan, schedule = _load_matching(Path(args.plan), Path(args.schedule))
    print(format_estimate(estimate(schedule, plan)))
    totals = _open_ledger(paths.ledger).totals()
    print(f"ledger: spent={totals.spent_usd:.6f} outstanding={totals.outstanding_usd:.6f} "
          f"remaining={plan.cap_usd - totals.spent_usd:.6f} (cap {plan.cap_usd:.6f} USD)")
    return 0


# ---------------------------------------------------------------- run


def _cmd_run(args: argparse.Namespace, paths: Paths, env: Mapping[str, str]) -> int:
    plan, schedule = _load_matching(Path(args.plan), Path(args.schedule))
    run_dir = paths.campaign_dir / args.run_id
    if args.paid:
        model_ids = {plan.profile(c.profile).model_id for c in schedule.calls
                     if c.service is Service.TRANSLATE and c.profile is not None}
        try:
            auth = money.authorize_paid(paid_flag=True, budget_usd=args.budget_usd, plan=plan,
                                        model_ids=model_ids, env=env)
            backends: Backends | None = real_backends(auth, plan)
        except PaidCallRefused as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_REFUSED
        budget, ledger, code_ref = auth.budget_usd, Ledger(paths.ledger), git_code_ref()
    else:
        backends, code_ref = None, None
        budget = plan.cap_usd if args.budget_usd is None else args.budget_usd
        ledger = _open_ledger(paths.ledger)
    result = Runner(schedule, plan, run_dir=run_dir, run_id=args.run_id, ledger=ledger, backends=backends,
                    budget_usd=budget, code_ref=code_ref).run()
    print(_dump(asdict(result)))
    return 0


# ---------------------------------------------------------------- provenance readers


@dataclass(frozen=True, slots=True)
class RunProv:
    """Terminal state, attempts and outputs of a run, read from its prov.jsonl."""

    terminal: dict[str, Activity]  # call_id -> last terminal activity
    attempts: Counter[str]  # call_id -> service attempts
    interrupted: int
    outputs: dict[str, Entity]  # activity id -> output entity
    activities: tuple[Activity, ...]


def _read_run(run_dir: Path) -> RunProv:
    prov = run_dir / "prov.jsonl"
    if not prov.exists():
        raise CliError(f"no provenance store at {prov}")
    records = ProvStore(prov).read()
    entities = {r.id: r for r in records if isinstance(r, Entity)}
    outputs = {r.object: entities[r.subject] for r in records
               if isinstance(r, Relation) and r.kind is RelationKind.WAS_GENERATED_BY and r.subject in entities}
    activities = tuple(r for r in records if isinstance(r, Activity))
    terminal: dict[str, Activity] = {}
    attempts: Counter[str] = Counter()
    interrupted = 0
    for a in activities:
        if a.kind == KIND_ORPHAN:
            interrupted += 1
        elif a.attrs.get("call_id") is not None:
            if a.kind in (KIND_ACM, KIND_TRANSLATE):
                attempts[a.attrs["call_id"]] += 1
            if a.attrs.get("terminal") in TERMINAL_STATES:
                terminal[a.attrs["call_id"]] = a
    return RunProv(terminal, attempts, interrupted, outputs, activities)


def _cmd_status(args: argparse.Namespace, paths: Paths, env: Mapping[str, str]) -> int:
    run_dir = paths.campaign_dir / args.run_id
    prov = _read_run(run_dir)
    counts: dict[str, Counter[str]] = {}
    if args.schedule:
        for c in Schedule.load(Path(args.schedule)).calls:
            done = prov.terminal.get(c.call_id)
            state = "pending" if done is None else done.attrs["terminal"]
            counts.setdefault(str(c.condition), Counter())[state] += 1
    else:
        for a in prov.terminal.values():
            counts.setdefault(str(a.attrs["condition"]), Counter())[a.attrs["terminal"]] += 1
    ledger = _open_ledger(paths.ledger)
    outstanding = sum(float(e["usd"]) for e in ledger.outstanding(args.run_id))
    versions = sorted({a.model_returned for a in prov.activities
                       if a.kind in (KIND_ACM, KIND_TRANSLATE) and a.status == "ok" and a.model_returned})
    print(_dump({
        "run_id": args.run_id,
        "calls": {cond: {s: c.get(s, 0) for s in (*TERMINAL_STATES, "pending")} for cond, c in sorted(counts.items())},
        "attempts": sum(prov.attempts.values()),
        "interrupted_attempts": prov.interrupted,
        "run_spent_usd": ledger.totals().run_spent_usd.get(args.run_id, 0.0),
        "run_outstanding_usd": outstanding,
        "model_versions": versions,
    }))
    return 0


# ---------------------------------------------------------------- compare


def _read_output(run_dir: Path, entity: Entity | None, attr: str) -> bytes | None:
    rel = None if entity is None else entity.attrs.get(attr)
    return None if rel is None else (run_dir / rel).read_bytes()


def _acm_observation(run_dir: Path, prov: RunProv, call_id: str, a: Activity) -> compare.AcmObservation:
    condition, med, profile = a.attrs["condition"], a.attrs["medication"], a.attrs["profile"]
    key = f"{condition}|{med}" if profile is None else f"{condition}|{med}|{profile}"
    entity = prov.outputs.get(a.id) if a.attrs["terminal"] == "ok" else None
    body = _read_output(run_dir, entity, "body_file")
    js = _read_output(run_dir, entity, "json_file")
    raw = None if body is None else compare.level1_sha256(body)
    level2 = None if js is None else compare.level2_sha256(json.loads(js.decode("utf-8")))
    # An ok call whose body or parsed response is missing cannot be compared: counted as failed, never as content.
    ok = a.attrs["terminal"] == "ok" and raw is not None and level2 is not None
    return compare.AcmObservation(call_id=call_id, key=key, model_version=a.model_returned, raw_sha256=raw,
                                  level2_sha256=level2, ok=ok)


def _translation_observation(run_dir: Path, prov: RunProv, call_id: str, a: Activity) -> compare.TranslationObservation:
    key = f"{a.attrs['medication']}|{a.attrs['profile']}"
    entity = prov.outputs.get(a.id) if a.attrs["terminal"] == "ok" else None
    raw = _read_output(run_dir, entity, "text_file")
    text = None if raw is None else raw.decode("utf-8")
    return compare.TranslationObservation(call_id=call_id, key=key, text=text,
                                          ok=a.attrs["terminal"] == "ok" and text is not None)


def _cmd_compare(args: argparse.Namespace, paths: Paths, env: Mapping[str, str]) -> int:
    run_dir = paths.campaign_dir / args.run_id
    prov = _read_run(run_dir)
    acm_obs, tr_obs = [], []
    for call_id, a in sorted(prov.terminal.items()):
        if a.attrs["condition"] == str(Condition.TRANSLATION_ISOLATED):
            tr_obs.append(_translation_observation(run_dir, prov, call_id, a))
        else:
            acm_obs.append(_acm_observation(run_dir, prov, call_id, a))
    rows = compare.summary_rows(compare.compare_acm(acm_obs), compare.compare_translations(tr_obs))
    text = _dump(rows)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


# ---------------------------------------------------------------- parser and main


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", help="default: env HAB_DATA_DIR or " + DEFAULT_DATA_DIR)
    common.add_argument("--ledger", help="default: <data-dir>/campaign/ledger.jsonl")
    common.add_argument("--campaign-dir", help="default: <data-dir>/campaign")

    parser = argparse.ArgumentParser(prog="python -m habench.campaign", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("plan-smoke", "plan-pilot"):
        p = sub.add_parser(name, parents=[common], help=f"write the {name[5:]} schedule")
        p.add_argument("--plan", required=True)
        p.add_argument("--manifest", help="default: repro/split_manifest.csv")
        p.add_argument("--snapshots", help="default: <data-dir>/snapshots")
        p.add_argument("--out", required=True)

    p = sub.add_parser("estimate", parents=[common], help="call counts, worst-case cost and ledger totals")
    p.add_argument("--schedule", required=True)
    p.add_argument("--plan", required=True)

    p = sub.add_parser("run", parents=[common], help="execute a schedule (dry run unless --paid)")
    p.add_argument("--schedule", required=True)
    p.add_argument("--plan", required=True)
    p.add_argument("--run-id", required=True, type=_run_id)
    p.add_argument("--paid", action="store_true")
    p.add_argument("--budget-usd", type=float)

    p = sub.add_parser("status", parents=[common], help="state of a run from its provenance and the ledger")
    p.add_argument("--run-id", required=True, type=_run_id)
    p.add_argument("--schedule", help="needed to count pending calls")

    p = sub.add_parser("compare", parents=[common], help="repeatability summary of a run")
    p.add_argument("--run-id", required=True, type=_run_id)
    p.add_argument("--out")
    return parser


_COMMANDS = {"plan-smoke": _cmd_plan, "plan-pilot": _cmd_plan, "estimate": _cmd_estimate, "run": _cmd_run,
             "status": _cmd_status, "compare": _cmd_compare}


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else EXIT_USAGE)
    try:
        return _COMMANDS[args.command](args, _resolve_paths(args, env), env)
    except (CliError, PlanError, RunError, SealedError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
