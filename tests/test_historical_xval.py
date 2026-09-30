"""Offline tests for the hybrid cross-validation: sampling, patching link@405a10c, coverage table, comparison."""

from __future__ import annotations

import json

import pytest

from habench.historical import xval
from habench.pipeline import catalog
from habench.pipeline.catalog import TRAIT_RULES, Config


@pytest.fixture(scope="module")
def source() -> str:
    try:
        return xval.load_source()
    except (OSError, ValueError, xval.subprocess.CalledProcessError):
        pytest.skip("HealDB git repository (blob c9c4aeb) not available")


def test_lattice_size_and_membership():
    cells = xval.lattice()
    assert len(cells) == 128 == len(set(cells))
    assert catalog.V1 in cells and catalog.V1_EXTEND in cells


def test_sample_deterministic_size_and_required():
    a, b = xval.sample_hybrids(), xval.sample_hybrids()
    assert a == b and len(a) == 100 == len(set(a))
    assert a[0] == catalog.V1 and a[1] == catalog.V1.with_(map="cm_ungated")
    assert set(a) <= set(xval.lattice())
    assert xval.sample_hybrids(100, seed=1) != a


def test_cfg_id_stable():
    assert xval.cfg_id(catalog.V1) == xval.cfg_id(Config.of(catalog.V1.as_dict()))
    assert len(xval.cfg_id(catalog.V1)) == 10
    ids = [xval.cfg_id(c) for c in xval.lattice()]
    assert len(set(ids)) == 128
    assert xval.cfg_id(catalog.V1) != xval.cfg_id(catalog.V1.with_(ent_thr=0.65))


def test_patch_identity_for_v1(source):
    assert xval.patch_link(source, catalog.V1) == source


def test_patch_every_sampled_config(source):
    for cfg in xval.sample_hybrids():
        out = xval.patch_link(source, cfg)
        compile(out, f"<{xval.cfg_id(cfg)}>", "exec")
        rule = TRAIT_RULES[cfg["trait"]]
        assert f"vl_score >= {cfg['icd_thr']!r} and vl_entity_score >= {cfg['ent_thr']!r}:" in out
        gate_present = "# Skip if CID does not exist" in out
        assert gate_present == (cfg["map"] == "cm_gated")
        assert ("search_repository_icd(cursor, icd_full_nodot)" in out)
        assert ('"LOW_CONFIDENCE"' in out.split("# Trait filtering")[1].split("# Select main trait")[0]) == (
            "LOW_CONFIDENCE" in rule.veto
        )
        assert ("valid_trait" in out) == (rule.required is not None)
        hyp = "> 0.65 for t in traits" in out
        assert hyp == (cfg["trait"] in ("v1", "v1_no_required"))
        assert ("> 0.6 for t in traits" in out) == (cfg["trait"] == "v1_hyp_le_0.6")
        if cfg["trait"] == "neg_only":
            assert 'if trait_names & {"NEGATION"}:' in out and 't[0] == "HYPOTHETICAL"' not in out


def test_patch_asserts_single_match(source):
    with pytest.raises(ValueError):
        xval.patch_link(source + "\n" + "if vl_score >= 0.6 and vl_entity_score >= 0.6:\n", catalog.V1)
    with pytest.raises(ValueError):
        xval.patch_link(source.replace("if vl_score >= 0.6 and vl_entity_score >= 0.6:", "if True:"), catalog.V1)


def test_write_patched_retargets_schema(source, tmp_path):
    cfgs = xval.write_patched(tmp_path, source=source, n=10)
    entries = json.loads((tmp_path / "configs.json").read_text())
    assert [e["cfg_id"] for e in entries] == [xval.cfg_id(c) for c in cfgs]
    for c in cfgs:
        text = (tmp_path / f"{xval.cfg_id(c)}.py").read_text()
        assert "healdb.hd_" not in text and "healdb_xval.hd_medication_disease" in text
        compile(text, "<patched>", "exec")


def test_coverage_table_mentions_every_factor_and_level():
    table = xval.coverage_table()
    for name, f in catalog.FACTORS.items():
        assert f"`{name}`" in table
        for level in f.levels:
            assert f"| `{name}` | `{level}` |" in table
    assert "who_exact_fb" in table and "catalogado, não executado" in table
    row = {line.split("|")[1].strip() + line.split("|")[2].strip(): line for line in table.splitlines()[2:]}
    assert "sim" in row["`trait``neg_only`"] and "não" in row["`trait``v2`"]
    assert "não" in row["`occ``per_entity_any`"] and "não" in row["`dup_ind``True`"]


def test_expected_and_compare_all(tmp_path):
    from habench.historical.replay import write_tsv
    from habench.pipeline.tables_v1 import MD_COLUMNS

    calls = []

    def fake_expected(cfg, ev, hier):
        calls.append(cfg)
        return [{c: (i if c == "id_med_disease" else 1) for c in MD_COLUMNS} | {
            "cd_icd_full": "A01", "id_icd_group": None, "id_icd_cat": None, "id_icd_subcat": None, "vl_score": 0.7,
            "vl_entity_score": 0.8, "nm_trait_main": None, "vl_trait_main_score": None, "fl_low_confidence": 0,
        } for i in (1, 2)]

    cfgs = xval.sample_hybrids(3)
    (tmp_path / "configs.json").write_text(json.dumps([{"cfg_id": xval.cfg_id(c), "config": c.as_dict()} for c in cfgs]))
    rows = fake_expected(cfgs[0], None, None)
    write_tsv(tmp_path / f"{xval.cfg_id(cfgs[0])}.tsv", MD_COLUMNS, rows)
    write_tsv(tmp_path / f"{xval.cfg_id(cfgs[1])}.tsv", MD_COLUMNS, rows[:1])
    orig = xval.expected
    xval.expected = fake_expected
    try:
        res = xval.compare_all(tmp_path, ev_dev=object(), hier=object())
    finally:
        xval.expected = orig
    assert [r["status"] for r in res] == ["compared", "compared", "missing"]
    assert res[0]["equal"] and not res[1]["equal"] and res[1]["n_only_expected"] == 1
