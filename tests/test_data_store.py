import hashlib
import json

import pyarrow as pa
import pytest

from habench.data import dumps, store

TABLE = "hd_int_med_disease_api_response"
API_1 = '{"ModelVersion": "3.0.0", "a": "x\\ny"}'
API_2 = '{"k": "café"}'


def make_dump(root):
    d = root / "dumps" / "src"
    d.mkdir(parents=True)
    body = (
        f"CREATE TABLE `{TABLE}` (\n"
        "  `id_medication` int NOT NULL,\n"
        "  `ds_api_response` longtext,\n"
        "  `vl_x` double DEFAULT NULL,\n"
        "  `nm` varchar(9) DEFAULT NULL,\n"
        "  `fl` tinyint(1) DEFAULT NULL,\n"
        "  PRIMARY KEY (`id_medication`)\n) ENGINE=InnoDB;\n"
        f"INSERT INTO `{TABLE}` VALUES "
        "(4,'{\"ModelVersion\": \"3.0.0\", \"a\": \"x\\\\ny\"}',0.6668867468833923,NULL,1),"
        "(5,NULL,3,NULL,NULL);\n"
        f"INSERT INTO `{TABLE}` VALUES (6,'{API_2}',-1e-3,NULL,0);\n"
    )
    (d / f"healdb_{TABLE}.sql").write_text(body, encoding="utf-8", newline="\n")
    return d


@pytest.fixture
def env(tmp_path, monkeypatch):
    make_dump(tmp_path)
    monkeypatch.setattr(dumps, "DUMPS_DIR", tmp_path / "dumps")
    monkeypatch.setitem(dumps.SOURCES, "V1", "src")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    monkeypatch.setitem(store.SNAPSHOT_TABLES, "v1", (TABLE,))
    return tmp_path


def test_round_trip(env):
    man = store.build_snapshot("v1")
    e = man[TABLE]
    assert e["rows"] == 3
    assert e["columns"] == ["id_medication", "ds_api_response", "vl_x", "nm", "fl", "ds_api_response_sha256"]
    assert e["source_bytes"] == (env / "dumps/src" / f"healdb_{TABLE}.sql").stat().st_size
    assert e["snapshot_sha256"] == hashlib.sha256(store.snapshot_path("v1", TABLE).read_bytes()).hexdigest()
    assert store.manifest("v1") == json.loads((env / "data/snapshots/v1/manifest.json").read_text())
    assert "built_at" in e and e["source_file"].endswith(f"healdb_{TABLE}.sql")

    t = store.load_table("v1", TABLE)
    assert t.schema.field("id_medication").type == pa.int64()
    assert t.schema.field("vl_x").type == pa.float64()
    assert t.schema.field("nm").type == pa.string()
    assert t.schema.field("fl").type == pa.int64()
    recs = store.load_records("v1", TABLE)
    assert [r["id_medication"] for r in recs] == [4, 5, 6]
    assert recs[0]["vl_x"] == 0.6668867468833923
    assert recs[1]["vl_x"] == 3.0 and type(recs[1]["vl_x"]) is float
    assert recs[2]["vl_x"] == -0.001
    assert recs[0]["ds_api_response"] == API_1
    assert recs[0]["ds_api_response_sha256"] == hashlib.sha256(API_1.encode()).hexdigest()
    assert recs[1]["ds_api_response"] is None and recs[1]["ds_api_response_sha256"] is None
    assert recs[2]["ds_api_response_sha256"] == hashlib.sha256(API_2.encode()).hexdigest()
    assert store.load_table("v1", TABLE, ["id_medication"]).column_names == ["id_medication"]


def test_deterministic_parquet(env):
    store.build_snapshot("v1")
    first = store.snapshot_path("v1", TABLE).read_bytes()
    store.build_snapshot("v1", force=True)
    assert store.snapshot_path("v1", TABLE).read_bytes() == first


def test_skip_if_unchanged(env):
    m1 = store.build_snapshot("v1")
    m2 = store.build_snapshot("v1")
    assert m2[TABLE]["built_at"] == m1[TABLE]["built_at"]
    src = env / "dumps/src" / f"healdb_{TABLE}.sql"
    src.write_text(src.read_text(encoding="utf-8").replace("(6,", "(7,"), encoding="utf-8", newline="\n")
    m3 = store.build_snapshot("v1")
    assert m3[TABLE]["source_sha256"] != m1[TABLE]["source_sha256"]
    assert [r["id_medication"] for r in store.load_records("v1", TABLE)] == [4, 5, 7]


def test_force_rebuilds_and_bad_table(env):
    m1 = store.build_snapshot("v1")
    assert store.build_snapshot("v1", force=True)[TABLE]["snapshot_sha256"] == m1[TABLE]["snapshot_sha256"]
    with pytest.raises(ValueError):
        store.build_snapshot("v1", ["hd_nope"])


def test_cli_usage():
    assert store.main(["bogus"]) == 2


# ---- real dumps -------------------------------------------------------------------------------------------

EXPECTED = {
    ("v1", "hd_int_med_disease_api_response"): 7447,
    ("v2", "hd_int_med_disease_api_response"): 7447,
    ("g0327", "hd_int_med_disease_api_response"): 7447,
    ("g0327", "hd_translate_eng_leaflet_section"): 7473,
    ("v1", "hd_int_med_disease_entity"): 274010,
    ("v1", "hd_int_med_disease_trait"): 469957,
    ("v1", "hd_medication_disease"): 43194,
    ("v1", "hd_medication_disease_extend"): 44233,
    ("v2", "hd_int_med_disease_entity_icd"): 375595,
    ("v2", "hd_int_med_disease_entity_trait"): 107543,
    ("v2", "hd_int_med_disease_cutoff_audit"): 75119,
    ("v2", "hd_medication_disease"): 27861,
    ("v1", "hd_translate_eng_leaflet_section"): 7473,
    ("v2", "hd_translate_eng_leaflet_section"): 7473,
    ("v1", "hd_medication"): 10548,
    ("v1", "hd_icd_group"): 275,
    ("v1", "hd_icd_category"): 2045,
    ("v1", "hd_icd_subcategory"): 12451,
}


@pytest.fixture(scope="session")
def real_snapshots():
    # No monkeypatching here: builds only the missing snapshots under the real DATA_DIR.
    for snap in store.SNAPSHOT_TABLES:
        store.build_snapshot(snap)


@pytest.mark.dumps
@pytest.mark.parametrize(("snap", "table"), sorted(EXPECTED))
def test_real_row_counts(real_snapshots, snap, table):
    import pyarrow.parquet as pq

    n = EXPECTED[(snap, table)]
    assert store.manifest(snap)[table]["rows"] == n
    assert pq.ParquetFile(store.snapshot_path(snap, table)).metadata.num_rows == n


@pytest.mark.dumps
def test_real_v1_medication_4(real_snapshots):
    t = store.load_table("v1", TABLE)
    recs = [r for r in t.to_pylist() if r["id_medication"] == 4]
    assert recs
    for r in recs:
        assert json.loads(r["ds_api_response"])["ModelVersion"] == "3.0.0.20231001"
        assert r["ds_api_response_sha256"] == hashlib.sha256(
            r["ds_api_response"].encode("utf-8", "surrogateescape")).hexdigest()
