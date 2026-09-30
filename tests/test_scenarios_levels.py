"""Levels, the sealed test levels, the sealed partition and the YAML catalogue."""

import json

import pytest
import yaml
from test_scenarios_data import SEED, toy_group

from habench.data import splits
from habench.oracle import toy
from habench.pipeline import catalog
from habench.scenarios import config, levels
from habench.scenarios.generate import generate, generate_with_report, manifest_groups
from habench.types import SealedError


def test_dev_cal_levels_follow_spec_4_1():
    lv = levels.levels("dev")
    assert lv["ent_thr"] == (0.55, 0.60, 0.65, 0.70)
    assert lv["icd_thr"] == (0.30, 0.55, 0.60, 0.65)
    assert lv == levels.levels("cal")
    assert lv["trait"] == catalog.FACTORS["trait"].levels and lv["map"] == catalog.FACTORS["map"].levels
    assert catalog.V1["ent_thr"] in lv["ent_thr"] and catalog.V2["icd_thr"] in lv["icd_thr"]


def test_test_levels_are_sealed_until_the_freeze(tmp_path, monkeypatch):
    monkeypatch.setenv("HAB_DATA_DIR", str(tmp_path))
    with pytest.raises(SealedError):
        levels.test_levels()
    assert not (tmp_path / "truth").exists()  # nothing was created
    sealed = tmp_path / "truth" / "sealed"
    sealed.mkdir(parents=True)
    (sealed / "test_levels.json").write_text(json.dumps({"ent_thr": [0.575], "icd_thr": [0.475]}))
    assert levels.test_levels() == {"ent_thr": (0.575,), "icd_thr": (0.475,)}  # read at call time from HAB_DATA_DIR


def test_test_partition_raises_sealed_error_before_touching_data(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("data was touched")

    monkeypatch.setattr(splits, "evidence_for", boom)
    monkeypatch.setattr("habench.pipeline.evidence.load_evidence", boom)
    with pytest.raises(SealedError):
        levels.levels("test")
    with pytest.raises(SealedError):
        manifest_groups("test")
    with pytest.raises(SealedError):
        generate("test", seed=SEED)
    with pytest.raises(ValueError):
        generate("reserve", seed=SEED)


def test_explicit_groups_with_test_medications_are_sealed():
    test_med = splits._manifest()[0]["test"][0]
    _, ev = toy_group()
    with pytest.raises(SealedError):
        generate_with_report("dev", seed=SEED, groups=[("gt", (test_med,))], evidence=ev, hier=toy.hierarchy())


def test_manifest_groups_are_dev_or_cal_only():
    part_of = splits._manifest()[1]
    for p in ("dev", "cal"):
        gs = manifest_groups(p)
        assert gs and all(part_of[m] == p for _, meds in gs for m in meds)


def test_yaml_catalogue_matches_python_constants():
    cfg = config.load_config()
    assert cfg.max_changed == 25 and cfg.max_unchanged == 25
    assert cfg.raw["families"]["P"]["generated"] is False
    assert set(cfg.raw["families"]["P"]["factors"]) == {"dup_ind", "mask_drug", "wow_rewrite", "cut10k"}
    assert "contrafactual_indisponivel" in cfg.raw["families"]["P"]["note"]
    from habench.scenarios import queries

    assert (queries.MAX_CHANGED, queries.MAX_UNCHANGED) == (cfg.max_changed, cfg.max_unchanged)
    for f, want in levels.dev_cal_levels().items():
        assert set(cfg.raw["levels"][f]) == set(want)
    F = cfg.family("F")["changes"]
    assert all(t in levels.DEV_CAL_THRESHOLDS["ent_thr"] for t in F["ent_thr"])
    assert all(t in levels.DEV_CAL_THRESHOLDS["icd_thr"] for t in F["icd_thr"])
    assert set(F["trait"]) <= set(catalog.TRAIT_RULES)
    for a, b in cfg.family("M")["pairs"]:
        assert a in catalog.MAP_LEVELS and b in catalog.MAP_LEVELS


def test_yaml_with_inconsistent_levels_is_rejected(tmp_path):
    raw = yaml.safe_load(config.CATALOG_PATH.read_text(encoding="utf-8"))
    raw["levels"]["ent_thr"] = [0.575, 0.625]
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match="levels"):
        config.load_config(p)
