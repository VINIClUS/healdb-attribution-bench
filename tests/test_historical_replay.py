"""Offline tests for the replay side: driver formatter, TSV round trip, comparison, log parsing, secret scan."""

from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
import types
from pathlib import Path

import pytest

from habench.historical import replay
from habench.pipeline.tables_v1 import ENTITY_COLUMNS, MD_COLUMNS

REPLAY_SCRIPTS = Path(__file__).parents[1] / "scripts" / "replay"


@pytest.fixture(scope="module")
def driver():
    if "mysql.connector" not in sys.modules:
        mysql = types.ModuleType("mysql")
        connector = types.ModuleType("mysql.connector")
        mysql.connector = connector
        sys.modules.setdefault("mysql", mysql)
        sys.modules.setdefault("mysql.connector", connector)
    spec = importlib.util.spec_from_file_location("replay_driver", REPLAY_SCRIPTS / "driver.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VALUES = [None, 0, -3, 7, 0.1, 1e-07, 1.0, 0.30000000000000004, "plain", "tab\there", "nl\nx", "cr\rx", "back\\slash",
          "\\N", "a\\tb", b"bytes", True]


def test_driver_formatter_matches_replay_formatter(driver):
    for v in VALUES:
        assert driver.format_cell(v) == replay.format_cell(v)


def test_driver_formatter_round_trips_through_read_tsv(driver, tmp_path):
    kinds = {"i": "int", "f": "float", "s": "str"}
    rows = [
        {"i": 1, "f": 0.1, "s": "tab\there\\n"}, {"i": None, "f": 1e-07, "s": "nl\nx\r"}, {"i": 3, "f": None, "s": None},
        {"i": -4, "f": 0.30000000000000004, "s": "\\N"},
    ]
    path = tmp_path / "t.tsv"
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(kinds) + "\n")
        for r in rows:
            fh.write("\t".join(driver.format_cell(r[c]) for c in kinds) + "\n")
    assert replay.read_tsv(path, kinds) == rows


# ---- comparison ------------------------------------------------------------------------------------------


def _entity(med: int, code: str, score: float) -> dict:
    return {
        "id_medication": med, "cd_icd_full": code, "ds_icd": "d", "vl_score": score, "ds_icd_aggreg": "t",
        "vl_entity_score": 0.9, "tp_category": "MEDICAL_CONDITION", "nr_begin_offset": 0, "nr_end_offset": 3,
        "tp_entity": "DX_NAME", "ds_attributes": "[]",
    }


def _md(i: int) -> dict:
    return {
        "id_med_disease": i, "id_medication": 1, "cd_icd_full": "A01", "id_icd_group": 1, "id_icd_cat": 2,
        "id_icd_subcat": None, "vl_score": 0.7, "vl_entity_score": 0.8, "fl_low_confidence": 0,
        "nm_trait_main": "DIAGNOSIS", "vl_trait_main_score": 0.9,
    }


def _write_all(d: Path, entity: list[dict], trait: list[dict], md: list[dict]) -> None:
    replay.write_tsv(d / "entity.tsv", ENTITY_COLUMNS, entity)
    replay.write_tsv(d / "trait.tsv", replay.TRAIT_COLUMNS, trait)
    replay.write_tsv(d / "md.tsv", MD_COLUMNS, md)


def _theirs(entity, trait, md) -> dict:
    return {"entity": entity, "trait": trait, "md": md}


def test_compare_equal(tmp_path):
    ent = [_entity(1, "A01", 0.5), _entity(560, "C49.9", 0.25)]
    _write_all(tmp_path, ent, [], [_md(1)])
    res = replay.compare(tmp_path, _theirs(ent, [], [_md(1)]))
    assert res["equal"] and res["whitelisted"] == []
    assert res["whitelist_unused"] == [{"table": "entity", "key": [560, "C49.9"], "column": "vl_score"}]


def test_compare_whitelists_only_adjacent_doubles(tmp_path):
    snap = 0.123456789
    adjacent = math.nextafter(snap, 1.0)
    _write_all(tmp_path, [_entity(560, "C49.9", adjacent)], [], [])
    res = replay.compare(tmp_path, _theirs([_entity(560, "C49.9", snap)], [], []))
    assert res["equal"]
    assert [w["column"] for w in res["whitelisted"]] == ["vl_score"]
    assert res["whitelist_unused"] == []

    two_apart = math.nextafter(adjacent, 1.0)
    _write_all(tmp_path, [_entity(560, "C49.9", two_apart)], [], [])
    res = replay.compare(tmp_path, _theirs([_entity(560, "C49.9", snap)], [], []))
    assert not res["equal"] and res["whitelisted"] == []
    assert res["tables"]["entity"]["n_unexplained"] == 1


def test_compare_reports_unexplained_difference(tmp_path):
    # 1 ULP apart but not on the whitelisted key: still unexplained
    snap = 0.4
    _write_all(tmp_path, [_entity(1, "A01", math.nextafter(snap, 1.0))], [], [_md(1)])
    res = replay.compare(tmp_path, _theirs([_entity(1, "A01", snap)], [], [_md(1)]))
    assert not res["equal"]
    assert res["tables"]["entity"]["unexplained"][0]["key"] == [1, "A01"]

    other = dict(_md(1), nm_trait_main="SIGN")
    _write_all(tmp_path, [_entity(1, "A01", snap)], [], [other])
    res = replay.compare(tmp_path, _theirs([_entity(1, "A01", snap)], [], [_md(1)]))
    assert not res["equal"] and res["tables"]["md"]["n_unexplained"] == 1


def test_compare_reports_missing_and_extra_rows(tmp_path):
    _write_all(tmp_path, [], [], [_md(1), _md(2)])
    res = replay.compare(tmp_path, _theirs([], [], [_md(1), _md(3)]))
    assert not res["equal"]
    assert res["tables"]["md"]["n_only_replay"] == 1 and res["tables"]["md"]["n_only_snapshot"] == 1


# ---- logs ------------------------------------------------------------------------------------------------

LOG = [
    "[replay 2026-09-30 10:00:00] versions: python 3.12.4, mysql-connector-python 26.7.0, server 8.0.33",
    "[replay 2026-09-30 10:00:00] before: hd_int_med_disease_entity=0 hd_int_med_disease_trait=0 hd_medication_disease=0",
    "[replay 2026-09-30 10:00:01] start process_disease_data_json",
    "Error something in historical code",
    "[replay 2026-09-30 10:09:07] end process_disease_data_json: 546.2s | hd_int_med_disease_entity=10 "
    "hd_int_med_disease_trait=20 hd_medication_disease=0",
    "[replay 2026-09-30 10:09:07] OPERATOR ACTION: TRUNCATE hd_medication_disease (not in the historical code; "
    "V1 md ids start at 1)",
    "[replay 2026-09-30 10:11:35] end link_medications_with_diseases: 148.0s | hd_int_med_disease_entity=10 "
    "hd_int_med_disease_trait=20 hd_medication_disease=5",
    "[replay 2026-09-30 10:11:40] total 700.5s",
]


def test_parse_driver_log():
    p = replay.parse_driver_log(LOG)
    assert p["timings_s"] == {"process_disease_data_json": 546.2, "link_medications_with_diseases": 148.0}
    assert p["row_counts_after_stage"]["link_medications_with_diseases"]["hd_medication_disease"] == 5
    assert p["operator_actions"] == [
        "TRUNCATE hd_medication_disease (not in the historical code; V1 md ids start at 1)"
    ]
    assert p["versions"].startswith("python 3.12.4")
    assert p["total_s"] == 700.5 and p["historical_error_lines"] == 1
    assert p["fk_errors_by_constraint"] == {}


FK_LINE = ("Error inserting entity for id_medication=1, ICD=E84.9: 1452 (23000): Cannot add or update a child row: "
           "a foreign key constraint fails (`healdb`.`hd_int_med_disease_entity`, CONSTRAINT `FK_MEDICATION_ACM2` "
           "FOREIGN KEY (`id_medication`) REFERENCES `hd_medication` (`id_medication`))")


def test_manifest_records_setup_actions_and_failed_runs(tmp_path):
    (tmp_path / "replay_405a10c.log").write_text("\n".join(LOG) + "\n")
    (tmp_path / "run1.log").write_text("\n".join([FK_LINE, FK_LINE, LOG[-1]]) + "\n")
    m = replay.write_replay_manifest(
        tmp_path, tmp_path / "manifest.json", compare_result={"equal": True},
        setup_operator_actions=("load hd_medication",),
        failed_runs=({"driver_log": str(tmp_path / "run1.log"), "fix_commit": "abc"}, {"note": "no log"}),
    )
    assert m["setup_operator_actions"] == ["load hd_medication"]
    run1, other = m["failed_runs"]
    assert run1["fix_commit"] == "abc" and run1["replay"]["fk_errors_by_constraint"] == {"FK_MEDICATION_ACM2": 2}
    assert run1["replay"]["historical_error_lines"] == 2 and other == {"note": "no log"}
    assert json.loads((tmp_path / "manifest.json").read_text()) == m


def test_driver_log_lines_match_parser(driver, capsys):
    driver.log("end x: 1.0s | a=1")
    driver.log("OPERATOR ACTION: y")
    driver.log("total 2.0s")
    out = capsys.readouterr().out.splitlines()
    p = replay.parse_driver_log(out)
    assert p["timings_s"] == {"x": 1.0} and p["operator_actions"] == ["y"] and p["total_s"] == 2.0


# ---- secrets ---------------------------------------------------------------------------------------------

_ALLOWED_NAMES = re.compile(r"^(\$\{?(HAB_MYSQL_PASSWORD|MYSQL_ROOT_PASSWORD|MYSQL_PWD)|<|os\.environ\[)")


def test_no_hardcoded_passwords_in_scripts():
    files = [p for p in REPLAY_SCRIPTS.iterdir() if p.is_file()]
    assert len(files) >= 7
    bad = []
    for p in files:
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\s-p\S", line) and "pipefail" not in line:
                bad.append((p.name, n, line))
            for m in re.finditer(r"PASSWORD\s*=\s*(\S+)", line, flags=re.I):
                if not _ALLOWED_NAMES.match(m.group(1).strip("\"'")):
                    bad.append((p.name, n, line))
            for m in re.finditer(r"password\s*=\s*([\"'])", line):
                bad.append((p.name, n, line))
    assert bad == []
