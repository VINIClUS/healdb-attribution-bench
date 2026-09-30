import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from habench.campaign import cli
from habench.campaign.acm import AcmOutcome
from habench.campaign.calls import Schedule
from habench.campaign.runner import Backends
from habench.campaign.translate import TranslationOutcome

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "data" / "campaign" / "split_manifest.csv"
N_PILOT_CALLS = 30  # 2 texts x (3 ACM + 2 profiles x 3 x (translation + full pipeline))


def plan_dict(*, model_b: str = "fake.model-b") -> dict[str, Any]:
    return {
        "region": "us-east-2",
        "acm_price": {"usd_per_unit": 0.0005, "unit_chars": 100, "min_units": 1},
        "token_prices": {"fake.model-a": {"input_usd_per_mtok": 1.0, "output_usd_per_mtok": 2.0},
                         "fake.model-b": {"input_usd_per_mtok": 1.0, "output_usd_per_mtok": 2.0}},
        "profiles": [{"name": "pa", "model_id": "fake.model-a", "temperature": None},
                     {"name": "pb", "model_id": model_b, "temperature": 0.0}],
        "max_tokens": 100,
        "cap_usd": 100.0,
        "retry": {"max_attempts": 2, "backoff_s": 0.0, "retryable": ["ThrottlingException"]},
        "block_spacing_s": 0.0,
        "seed": 7,
        "smoke": {"texts": 1, "repetitions": 2},
        "pilot": {"texts": 2, "repetitions": 3, "references": 1, "blocks": 1},
        "price_source": "test fixture",
    }


def write_snapshots(root: Path) -> Path:
    v2 = root / "snapshots" / "v2"
    v2.mkdir(parents=True)
    pq.write_table(pa.table({"id_medication": [101, 102, 201],
                             "ds_text_submitted": ["texto submetido 101", "texto submetido 102",
                                                   "texto submetido 201"]}), v2 / "api_response.parquet")
    pq.write_table(pa.table({"id_medication": [101, 102, 201],
                             "ds_indication": ["indicado para hipertensao 101", "indicado para dor 102",
                                               "indicado para febre 201"]}),
                   v2 / "translate_eng_leaflet_section.parquet")
    return root / "snapshots"


class Setup:
    def __init__(self, tmp_path: Path, *, model_b: str = "fake.model-b") -> None:
        self.root = tmp_path / "work"
        self.root.mkdir()
        self.plan = self.root / "plan.yaml"
        self.plan.write_text(yaml.safe_dump(plan_dict(model_b=model_b)), encoding="utf-8")
        self.snapshots = write_snapshots(self.root)
        self.schedule = self.root / "pilot.json"
        self.data_dir = self.root / "data"
        self.ledger = self.root / "ledger.jsonl"
        self.campaign = self.root / "campaign"

    def common(self) -> list[str]:
        return ["--data-dir", str(self.data_dir), "--ledger", str(self.ledger), "--campaign-dir", str(self.campaign)]

    def plan_pilot(self) -> int:
        return cli.main(["plan-pilot", "--plan", str(self.plan), "--manifest", str(MANIFEST),
                         "--snapshots", str(self.snapshots), "--out", str(self.schedule), *self.common()], env={})

    def run_args(self, run_id: str, *extra: str) -> list[str]:
        return ["run", "--schedule", str(self.schedule), "--plan", str(self.plan), "--run-id", run_id,
                *self.common(), *extra]


@pytest.fixture
def setup(tmp_path: Path) -> Setup:
    s = Setup(tmp_path)
    assert s.plan_pilot() == 0
    return s


def files(root: Path) -> set[Path]:
    return {p for p in root.rglob("*")}


def test_plan_smoke_and_pilot(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    s = Setup(tmp_path)
    smoke = s.root / "smoke.json"
    assert cli.main(["plan-smoke", "--plan", str(s.plan), "--manifest", str(MANIFEST),
                     "--snapshots", str(s.snapshots), "--out", str(smoke), *s.common()], env={}) == 0
    out = capsys.readouterr().out
    assert "2 calls" in out and "excluded medications: 0" in out
    assert Schedule.load(smoke).kind == "smoke"
    assert s.plan_pilot() == 0
    sched = Schedule.load(s.schedule)
    assert sched.kind == "pilot" and len(sched.calls) == N_PILOT_CALLS
    assert {c.medication for c in sched.calls} == {101, 201}  # test and reserve groups never used


def test_estimate_prints_ledger_totals(setup: Setup, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    assert cli.main(["estimate", "--schedule", str(setup.schedule), "--plan", str(setup.plan), *setup.common()],
                    env={}) == 0
    out = capsys.readouterr().out
    assert "total USD, one attempt" in out
    assert "ledger: spent=0.000000 outstanding=0.000000 remaining=100.000000" in out
    assert not setup.ledger.exists()  # estimate never creates the ledger


def test_plan_hash_mismatch_refused(setup: Setup, capsys: pytest.CaptureFixture[str]) -> None:
    changed = plan_dict()
    changed["cap_usd"] = 50.0
    setup.plan.write_text(yaml.safe_dump(changed), encoding="utf-8")
    for cmd in (["estimate"], ["run", "--run-id", "r1"]):
        argv = [*cmd, "--schedule", str(setup.schedule), "--plan", str(setup.plan), *setup.common()]
        assert cli.main(argv, env={}) == 2
    assert "plan hash mismatch" in capsys.readouterr().err
    assert not setup.campaign.exists()


def test_dry_run_writes_nothing(setup: Setup, capsys: pytest.CaptureFixture[str]) -> None:
    before = files(setup.root)
    capsys.readouterr()
    assert cli.main(setup.run_args("dry1"), env={}) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "dry_run" and result["n_planned"] == N_PILOT_CALLS
    assert files(setup.root) == before


def test_dry_run_does_not_import_boto3(setup: Setup) -> None:
    code = ("import sys\nfrom habench.campaign import cli\n"
            f"rc = cli.main({setup.run_args('dry2')!r}, env={{}})\n"
            "print(rc, 'boto3' in sys.modules, 'botocore' in sys.modules)")
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert proc.stdout.strip().splitlines()[-1] == "0 False False"


def test_bad_run_id_refused(setup: Setup) -> None:
    assert cli.main(setup.run_args("bad/id"), env={}) == 2


@pytest.fixture
def no_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*a: object, **k: object) -> Backends:
        pytest.fail("real_backends must not be called when the paid call is refused")

    monkeypatch.setattr(cli, "real_backends", fail)


PAID_ENV = {"HAB_PAID_CALLS": "1"}


def test_paid_refused_without_env_flag(setup: Setup, no_backends: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(setup.run_args("p1", "--paid", "--budget-usd", "5"), env={}) == 3
    assert "HAB_PAID_CALLS" in capsys.readouterr().err
    assert not setup.campaign.exists() and not setup.ledger.exists()


def test_paid_refused_without_budget(setup: Setup, no_backends: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(setup.run_args("p2", "--paid"), env=PAID_ENV) == 3
    assert "--budget-usd" in capsys.readouterr().err
    assert not setup.campaign.exists() and not setup.ledger.exists()


def test_paid_refused_for_placeholder_model(tmp_path: Path, no_backends: None,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    s = Setup(tmp_path, model_b="<model-b-placeholder>")
    assert s.plan_pilot() == 0
    assert cli.main(s.run_args("p3", "--paid", "--budget-usd", "5"), env=PAID_ENV) == 3
    assert "no price entry" in capsys.readouterr().err
    assert not s.campaign.exists() and not s.ledger.exists()


def test_paid_flag_is_not_enough_without_paid_option(setup: Setup, no_backends: None) -> None:
    # env alone (no --paid) is a dry run and never builds backends
    assert cli.main(setup.run_args("p4", "--budget-usd", "5"), env=PAID_ENV) == 0
    assert not setup.campaign.exists()


class FakeBackends:
    def __init__(self) -> None:
        self.n_acm = 0
        self.n_translate = 0

    def backends(self) -> Backends:
        return Backends(acm=self.acm, translate=self.translate)

    def acm(self, text: str) -> AcmOutcome:
        self.n_acm += 1
        response = {"Entities": [{"Text": "hipertensao", "Score": 0.9}], "ModelVersion": "0.1.0",
                    "ResponseMetadata": {"RequestId": f"req-{self.n_acm}", "HTTPStatusCode": 200}}
        return AcmOutcome(True, "2026-01-01T00:00:00.000000Z", "2026-01-01T00:00:01.000000Z", 5.0, "us-east-2",
                          "https://fake.invalid", len(text), json.dumps(response).encode("utf-8"), response,
                          "0.1.0", f"req-{self.n_acm}", None, 200, None, None, None)

    def translate(self, profile: Any, prompt: str, max_tokens: int) -> TranslationOutcome:
        self.n_translate += 1
        text = "Indicated for hypertension."
        response = {"output": {"message": {"content": [{"text": text}]}}, "usage": {"inputTokens": 10,
                                                                                    "outputTokens": 5}}
        return TranslationOutcome(True, "2026-01-01T00:00:00.000000Z", "2026-01-01T00:00:01.000000Z", 5.0,
                                  "us-east-2", "https://fake.invalid", profile.model_id, profile.temperature,
                                  max_tokens, "0" * 64, json.dumps(response).encode("utf-8"), response, text,
                                  "end_turn", 10, 5, 4, f"req-t{self.n_translate}", None, 200, None, None, None)


def test_paid_run_status_and_compare(setup: Setup, monkeypatch: pytest.MonkeyPatch,
                                     capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeBackends()
    seen: list[object] = []

    def fake_real_backends(auth: object, plan: object) -> Backends:
        seen.append(auth)
        return fake.backends()

    monkeypatch.setattr(cli, "real_backends", fake_real_backends)
    capsys.readouterr()
    assert cli.main(setup.run_args("paid1", "--paid", "--budget-usd", "10"), env=PAID_ENV) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(seen) == 1
    assert result["status"] == "completed" and result["n_ok"] == N_PILOT_CALLS and result["n_failed"] == 0
    assert result["n_attempts"] == N_PILOT_CALLS and 0 < result["run_spent_usd"] <= 10
    assert (setup.campaign / "paid1" / "prov.jsonl").exists() and setup.ledger.exists()

    assert cli.main(["status", "--run-id", "paid1", "--schedule", str(setup.schedule), *setup.common()],
                    env={}) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["calls"] == {
        "acm_isolated": {"ok": 6, "failed": 0, "not_executed": 0, "pending": 0},
        "translation_isolated": {"ok": 12, "failed": 0, "not_executed": 0, "pending": 0},
        "full_pipeline": {"ok": 12, "failed": 0, "not_executed": 0, "pending": 0},
    }
    assert status["attempts"] == N_PILOT_CALLS and status["interrupted_attempts"] == 0
    assert status["run_outstanding_usd"] == 0 and status["run_spent_usd"] == result["run_spent_usd"]
    assert status["model_versions"] == ["0.1.0", "fake.model-a", "fake.model-b"]

    assert cli.main(["status", "--run-id", "paid1", *setup.common()], env={}) == 0  # without a schedule
    assert json.loads(capsys.readouterr().out)["calls"]["acm_isolated"]["ok"] == 6

    out_file = setup.root / "compare.json"
    assert cli.main(["compare", "--run-id", "paid1", "--out", str(out_file), *setup.common()], env={}) == 0
    rows = json.loads(out_file.read_text(encoding="utf-8"))
    acm_rows = {r["key"]: r for r in rows if r["kind"] == "acm"}
    assert set(acm_rows) == {"acm_isolated|101", "acm_isolated|201", "full_pipeline|101|pa",
                             "full_pipeline|101|pb", "full_pipeline|201|pa", "full_pipeline|201|pb"}
    for r in acm_rows.values():
        assert r["n_ok"] == 3 and r["n_distinct_level2"] == 1 and r["n_distinct_level1"] == 3
        assert r["n_pairs_differing_level2"] == 0
    tr_rows = {r["key"]: r for r in rows if r["kind"] == "translation"}
    assert set(tr_rows) == {"101|pa", "101|pb", "201|pa", "201|pb"}
    for r in tr_rows.values():
        assert r["n_ok"] == 3 and r["n_distinct_exact"] == 1 and r["edit_max"] == 0

    assert cli.main(["compare", "--run-id", "paid1", *setup.common()], env={}) == 0  # stdout variant
    assert json.loads(capsys.readouterr().out) == rows

    # resumable: a second paid invocation finds every call terminal and makes no new call
    assert cli.main(setup.run_args("paid1", "--paid", "--budget-usd", "10"), env=PAID_ENV) == 0
    assert fake.n_acm == 18 and fake.n_translate == 12


def test_status_and_compare_without_run(setup: Setup, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["status", "--run-id", "nope", *setup.common()], env={}) == 2
    assert cli.main(["compare", "--run-id", "nope", *setup.common()], env={}) == 2
    assert "no provenance store" in capsys.readouterr().err
