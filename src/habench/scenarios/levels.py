"""Factor levels for scenario generation (SPEC 4.1): dev/cal levels and the sealed test levels.

Only `ent_thr` and `icd_thr` have partition-specific levels. The test list is generated at the P4 freeze and
lives under `<HAB_DATA_DIR>/truth/sealed/test_levels.json`; until then every request for it raises `SealedError`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from habench.pipeline import catalog
from habench.types import SealedError

DEV_CAL_THRESHOLDS: dict[str, tuple[float, ...]] = {
    "ent_thr": (0.55, 0.60, 0.65, 0.70),
    "icd_thr": (0.30, 0.55, 0.60, 0.65),
}
CATEGORICAL_FACTORS = ("occ", "sel", "trait", "map")
GENERATED_PARTITIONS = ("dev", "cal")


def check_partition(partition: str) -> None:
    """SealedError for "test" (before any data is touched); ValueError for a partition without scenarios."""
    if partition == "test":
        raise SealedError("scenario generation for the sealed test partition is not allowed before the freeze")
    if partition not in GENERATED_PARTITIONS:
        raise ValueError(f"scenarios are generated for {GENERATED_PARTITIONS}, not {partition!r}")


def dev_cal_levels() -> dict[str, tuple]:
    """Levels of every post factor in dev/cal: threshold grids of SPEC 4.1, categorical levels of the catalog."""
    out: dict[str, tuple] = dict(DEV_CAL_THRESHOLDS)
    for f in CATEGORICAL_FACTORS:
        out[f] = catalog.FACTORS[f].levels
    return out


def levels(partition: str) -> dict[str, tuple]:
    check_partition(partition)
    return dev_cal_levels()


def sealed_levels_path() -> Path:
    data_dir = Path(os.environ.get("HAB_DATA_DIR", "/home/vinicius/hab-data"))  # read at call time
    return data_dir / "truth" / "sealed" / "test_levels.json"


def test_levels() -> dict[str, tuple[float, ...]]:
    """The sealed test levels of `ent_thr` and `icd_thr`; SealedError before the freeze (file absent)."""
    path = sealed_levels_path()
    if not path.exists():
        raise SealedError("test levels are sealed until the P4 freeze")
    obj = json.loads(path.read_text(encoding="utf-8"))
    out = {f: tuple(float(v) for v in obj[f]) for f in DEV_CAL_THRESHOLDS}
    if any(not vs for vs in out.values()):
        raise ValueError("test_levels.json must list levels for ent_thr and icd_thr")
    return out


test_levels.__test__ = False  # not a pytest test when imported into a test module
