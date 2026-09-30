"""Loader of `repro/scenario_catalog.yaml`: the generator reads its targets, caps and quotas from there."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from habench.data.splits import REPRO_DIR
from habench.scenarios import levels

CATALOG_PATH = REPRO_DIR / "scenario_catalog.yaml"
FAMILIES = ("N", "F", "M", "O", "X", "I", "P")


@dataclass(frozen=True)
class ScenarioConfig:
    raw: Mapping

    @property
    def max_changed(self) -> int:
        return int(self.raw["sampling"]["max_changed"])

    @property
    def max_unchanged(self) -> int:
        return int(self.raw["sampling"]["max_unchanged"])

    def family(self, name: str) -> Mapping:
        return self.raw["families"][name]


def load_config(path: Path | None = None) -> ScenarioConfig:
    raw = yaml.safe_load((path or CATALOG_PATH).read_text(encoding="utf-8"))
    cfg = ScenarioConfig(raw)
    _check(cfg)
    return cfg


def _check(cfg: ScenarioConfig) -> None:
    """The YAML levels are the dev/cal levels of `levels.py`; the catalogue has every family."""
    for f, want in levels.dev_cal_levels().items():
        got = tuple(cfg.raw["levels"][f])
        if set(got) != set(want):
            raise ValueError(f"scenario_catalog.yaml levels of {f} differ from the catalog: {got} vs {want}")
    missing = [f for f in FAMILIES if f not in cfg.raw["families"]]
    if missing:
        raise ValueError(f"scenario_catalog.yaml lacks families {missing}")
    x = cfg.family("X")
    if int(x["i_bundle"]) + int(x["i_components"]) + int(x["ii"]) + int(x["iii"]) != int(x["targets_per_group"]):
        raise ValueError("X: i + ii + iii must add up to targets_per_group")
    if cfg.family("P").get("generated") is not False:
        raise ValueError("family P is catalogued only")
