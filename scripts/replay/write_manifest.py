"""Write repro/replay_manifest.json from the logs of the Docker replay (run on the host, after down.sh).

  uv run python scripts/replay/write_manifest.py

Records the run that succeeded (logs/, export/, xval/xval_result.json from `python -m habench.historical.xval
compare`), the setup operator action added after the first run, and the failed first run with its logs.
"""

import json
from pathlib import Path

from habench.historical import replay

REPLAY = Path("/home/vinicius/hab-data/replay")
LOGS = REPLAY / "logs"
ORCH = Path("/home/vinicius/hab-data/orchestration")

SETUP_OPERATOR_ACTIONS = (
    "load healdb.hd_medication from the V1 dump (FK parent of hd_int_med_disease_entity via FK_MEDICATION_ACM2 "
    "and of hd_medication_disease); missing in the first run; added to scripts/replay/up.sh in 1c505b0",
)
FAILED_RUNS = ({
    "run": 1,
    "driver_log": str(LOGS / "replay_405a10c.run1_fk_failure.log"),
    "wrapper_log": str(ORCH / "docker_alpha.run1.log"),
    "outcome": "driver rc=0 but 0 rows exported (entity, trait, md); xval ran on empty tables (0 rows per config)",
    "cause": "up.sh loaded a table subset without hd_medication; every entity insert failed on FK_MEDICATION_ACM2 "
             "and the historical code only prints the error and continues",
    "classification": "environment finding (subset load broke FK integrity), not a pipeline difference",
    "fix_commit": "1c505b0",
    "fix": "up.sh loads hd_medication; driver.py exits non-zero when process_disease_data_json writes no entity rows",
},)


def main() -> None:
    xval_result = json.loads((REPLAY / "xval" / "xval_result.json").read_text(encoding="utf-8"))
    m = replay.write_replay_manifest(
        LOGS, xval_result=xval_result, setup_operator_actions=SETUP_OPERATOR_ACTIONS, failed_runs=FAILED_RUNS,
    )
    failed = m["failed_runs"][0]["replay"]
    print(f"replay: export {m['export']['row_counts']}, compare equal={m['compare']['equal']}, "
          f"whitelisted={len(m['compare']['whitelisted'])}, historical Error lines={m['replay']['historical_error_lines']}, "
          f"total {m['replay']['total_s']}s")
    print(f"failed run 1: Error lines={failed['historical_error_lines']}, FK={failed['fk_errors_by_constraint']}")
    print(f"xval: {sum(r.get('agrees', False) for r in m['xval'])}/{len(m['xval'])} agree, "
          f"{sum(bool(r.get('equal')) for r in m['xval'])} strict equal")


if __name__ == "__main__":
    main()
