"""Sources manifest (protocol P0): identity of every external input of the benchmark.

`build_manifest` recomputes hashes on disk; `check_manifest` rebuilds and reports mismatches
against a committed manifest. Nothing here opens archives or copies script contents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = Path("/home/vinicius/healdb-reconstrucao")
DUMPS_ROOT = WORKSPACE / "x"
REDU_DIR = WORKSPACE / "src" / "redu"
REDU_VERSIONS = WORKSPACE / "out" / "redu_versions.json"
REDU_DOI = "10.25824/redu/24I1FH"
SNAPSHOTS_DIR = Path("/home/vinicius/hab-data/snapshots")
SNAPSHOT_NAMES = ("v1", "v2", "g0327")
HEALDB_REPO = Path("/home/vinicius/code/HealDB")
COMMITS = ("0e43ed9", "405a10c", "c5b0db1", "4895898", "2d1dc7f", "8ea0479")
BLOB_COMMITS = ("405a10c", "8ea0479")
BLOB_PATHS = tuple(
    f"src/nlp_extraction/{name}.py"
    for name in (
        "extract_diseases_from_indications",
        "process_disease_data_json",
        "link_medications_with_diseases",
        "translate_leaflet_sections",
        "main_nlp_extraction",
    )
)
WORKSPACE_SCRIPTS = tuple(
    f"scripts/{name}"
    for name in (
        "dumprows.py",
        "acm_text_v1.py",
        "extend_analysis.py",
        "replay_up.sh",
        "replay_405a10c.sh",
        "replay_extend.sh",
        "replay_driver.py",
        "replay_compare.py",
        "extend_from_link_405a10c.patch",
    )
) + ("out/extend_amostra.csv",)
SHA256SUMS = REPO_ROOT / "docs" / "protocolo" / "SHA256SUMS"
DERIVED = ("repro/corpus_groups.csv", "repro/split_manifest.csv")
MANIFEST_PATH = REPO_ROOT / "repro" / "sources_manifest.json"
GENERATED_BY = "habench.historical.sources build"


def hash_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dumps_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _git(*args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(HEALDB_REPO), *args], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def redu_section(
    versions_path: Path = REDU_VERSIONS, redu_dir: Path = REDU_DIR
) -> dict[str, Any]:
    payload = json.loads(versions_path.read_text(encoding="utf-8"))
    files: dict[int, dict[str, Any]] = {}
    for version in payload["data"]:
        for entry in version["files"]:
            data = entry["dataFile"]
            record = files.setdefault(
                data["id"],
                {
                    "dataverse_file_id": data["id"],
                    "name": data["filename"],
                    "bytes_stated": data["filesize"],
                    "md5_stated": data["md5"],
                    "dataset_versions": [],
                    "file_versions": [],
                },
            )
            if version["versionNumber"] not in record["dataset_versions"]:
                record["dataset_versions"].append(version["versionNumber"])
            if entry["version"] not in record["file_versions"]:
                record["file_versions"].append(entry["version"])
    out = []
    for file_id in sorted(files):
        record = files[file_id]
        record["dataset_versions"].sort()
        record["file_versions"].sort()
        found = sorted(redu_dir.glob(f"{file_id}__*"))
        if found:
            path = found[0]
            md5 = hash_file(path, "md5")
            record["local"] = {
                "name": path.name,
                "bytes": path.stat().st_size,
                "md5": md5,
                "sha256": hash_file(path, "sha256"),
            }
            record["md5_match"] = md5 == record["md5_stated"]
        else:
            record["local"] = None
            record["md5_match"] = False
        out.append(record)
    return {"doi": REDU_DOI, "files": out}


def _snapshot_manifests(snapshots_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        name: json.loads((snapshots_dir / name / "manifest.json").read_text(encoding="utf-8"))
        for name in SNAPSHOT_NAMES
    }


def dumps_section(
    manifests: dict[str, dict[str, Any]], dumps_root: Path = DUMPS_ROOT
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for snapshot in manifests.values():
        for table_info in snapshot.values():
            path = Path(table_info["source_file"])
            rel = str(path.relative_to(dumps_root))
            out[rel] = {
                "bytes": path.stat().st_size,
                "sha256": hash_file(path, "sha256"),
                "sha256_in_snapshot_manifest": table_info["source_sha256"],
            }
    return out


def snapshots_section(manifests: dict[str, dict[str, Any]]) -> dict[str, Any]:
    import pyarrow

    return {
        "pyarrow_version": pyarrow.__version__,
        "note": "Parquet bytes may depend on the pyarrow version; snapshot_sha256 is from the build manifests.",
        "tables": {
            name: {
                table: {"rows": info["rows"], "snapshot_sha256": info["snapshot_sha256"]}
                for table, info in sorted(tables.items())
            }
            for name, tables in manifests.items()
        },
    }


def historical_code_section() -> dict[str, Any]:
    return {
        "repo": "HealDB",
        "commits": {commit: _git("rev-parse", f"{commit}^{{commit}}") for commit in COMMITS},
        "blobs": {
            commit: {path: _git("rev-parse", f"{commit}:{path}") for path in BLOB_PATHS}
            for commit in BLOB_COMMITS
        },
    }


def workspace_scripts_section(workspace: Path = WORKSPACE) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for rel in WORKSPACE_SCRIPTS:
        path = workspace / rel
        out[rel] = {"sha256": hash_file(path, "sha256")} if path.is_file() else None
    return out


def reports_section(sums_path: Path = SHA256SUMS) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        name = name.strip()
        path = Path(name) if name.startswith("/") else sums_path.parent / name
        local = hash_file(path, "sha256") if path.is_file() else None
        out[name] = {
            "sha256_listed": digest,
            "exists": local is not None,
            "sha256_local": local,
            "match": local == digest if local is not None else None,
        }
    return out


def derived_section(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    return {rel: {"sha256": hash_file(repo_root / rel, "sha256")} for rel in DERIVED}


def build_manifest() -> dict[str, Any]:
    manifests = _snapshot_manifests(SNAPSHOTS_DIR)
    return {
        "generated_by": GENERATED_BY,
        "redu": redu_section(),
        "dumps": dumps_section(manifests),
        "snapshots": snapshots_section(manifests),
        "historical_code": historical_code_section(),
        "workspace_scripts": workspace_scripts_section(),
        "reports": reports_section(),
        "derived": derived_section(),
    }


def write_manifest(path: Path = MANIFEST_PATH) -> None:
    path.write_text(dumps_json(build_manifest()), encoding="utf-8")


def _diff(expected: Any, actual: Any, prefix: str = "") -> list[str]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        out: list[str] = []
        for key in sorted(set(expected) | set(actual)):
            where = f"{prefix}/{key}"
            if key not in expected:
                out.append(f"{where}: missing in committed manifest")
            elif key not in actual:
                out.append(f"{where}: missing on recompute")
            else:
                out.extend(_diff(expected[key], actual[key], where))
        return out
    return [] if expected == actual else [f"{prefix}: committed {expected!r} != recomputed {actual!r}"]


def check_manifest(path: Path = MANIFEST_PATH) -> list[str]:
    committed = json.loads(path.read_text(encoding="utf-8"))
    return _diff(committed, build_manifest())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="habench.historical.sources")
    parser.add_argument("command", choices=("build", "check"))
    parser.add_argument("--path", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args(argv)
    if args.command == "build":
        write_manifest(args.path)
        return 0
    problems = check_manifest(args.path)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
