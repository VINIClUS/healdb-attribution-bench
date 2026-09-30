"""Hybrid cross-validation of the core against link@405a10c patched to sampled configurations (design §E).

The V1-expressible sublattice (ent_thr x icd_thr x trait x map, occ=last_upsert, sel=all) can be executed by the
historical SQL-driven code after exact textual substitutions of its constants. `sample_hybrids` picks ~100 cells,
`write_patched` materializes one patched file per cell, `scripts/replay/xval.sh` runs them against a dev-only schema
inside the Docker replay and `compare_all` checks every `md` export against `tables_v1._md_like`. Dev medications
only: the sealed test partition is never read.

CLI: `python -m habench.historical.xval {prepare|compare|coverage}`.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import random
import subprocess
import sys
from pathlib import Path

from habench.pipeline import catalog, mapping
from habench.pipeline.catalog import TRAIT_RULES, Config
from habench.pipeline.tables_v1 import _md_like, compare_rows

REPLAY_DIR = Path("/home/vinicius/hab-data/replay")
XVAL_DIR = REPLAY_DIR / "xval"
HEALDB_REPO = Path("/home/vinicius/code/HealDB")
LINK_PATH = "src/nlp_extraction/link_medications_with_diseases.py"
LINK_BLOB_PREFIX = "c9c4aeb"
SEED = 20260930
XVAL_SCHEMA = "healdb_xval"

ENT_THRS = (0.55, 0.60, 0.65, 0.70)
ICD_THRS = (0.30, 0.55, 0.60, 0.65)
TRAITS = ("v1", "v1_hyp_le_0.6", "v1_no_required", "neg_only")
MAPS = ("cm_gated", "cm_ungated")


# ---- sampling --------------------------------------------------------------------------------------------


def lattice() -> list[Config]:
    """All 128 V1-expressible cells in a fixed order."""
    return [
        Config.of({"occ": "last_upsert", "sel": "all", "ent_thr": e, "icd_thr": i, "trait": t, "map": m})
        for e, i, t, m in itertools.product(ENT_THRS, ICD_THRS, TRAITS, MAPS)
    ]


def cfg_id(cfg: Config) -> str:
    return hashlib.sha256(repr(cfg.items).encode()).hexdigest()[:10]


def sample_hybrids(n: int = 100, seed: int = SEED) -> list[Config]:
    """Deterministic sample of the sublattice; always contains V1 and V1 with map=cm_ungated."""
    required = [catalog.V1, catalog.V1.with_(map="cm_ungated")]
    rest = [c for c in lattice() if c not in required]
    if not len(required) <= n <= len(required) + len(rest):
        raise ValueError(f"n must be in [{len(required)}, {len(required) + len(rest)}]")
    picked = random.Random(seed).sample(rest, n - len(required))
    return required + sorted(picked, key=cfg_id)


# ---- patching link@405a10c -------------------------------------------------------------------------------

_SCORE_OLD = "if vl_score >= 0.6 and vl_entity_score >= 0.6:"
_VETO_OLD = 'if trait_names & {"LOW_CONFIDENCE", "NEGATION", "PERTAINS_TO_FAMILY"}:'
_HYP_OLD = 'if any(t[0] == "HYPOTHETICAL" and (t[1] or 0) > 0.65 for t in traits):\n                continue\n'
_HYP_CMP_OLD = '(t[1] or 0) > 0.65 for t in traits'
_REQUIRED_OLD = (
    "                valid_trait = any(\n"
    '                    (t[0] in {"DIAGNOSIS", "SYMPTOM", "SIGN"} or\n'
    '                     (t[0] == "HYPOTHETICAL" and (t[1] or 0) <= 0.6))\n'
    "                    for t in traits\n"
    "                )\n"
    "                if not valid_trait:\n"
    "                    continue\n"
)
_GATE_START = "            # Skip if CID does not exist in category or subcategory tables\n"
_GATE_END = "            # Trait filtering\n"
_GATE_LINES = 23  # lines 110-132 of link@405a10c


def _sub(src: str, old: str, new: str) -> str:
    if src.count(old) != 1:
        raise ValueError(f"expected exactly one match of {old!r}, found {src.count(old)}")
    return src.replace(old, new)


def patch_link(source: str, cfg: Config) -> str:
    """Apply the constants of `cfg` to link@405a10c by exact textual substitutions (each must match once)."""
    rule = TRAIT_RULES[cfg["trait"]]
    out = _sub(source, _SCORE_OLD, f"if vl_score >= {float(cfg['icd_thr'])!r} and vl_entity_score >= {float(cfg['ent_thr'])!r}:")
    if rule.veto != TRAIT_RULES["v1"].veto:
        literal = "{" + ", ".join(f'"{n}"' for n in sorted(rule.veto)) + "}"
        out = _sub(out, _VETO_OLD, f"if trait_names & {literal}:")
    if rule.hyp_veto_gt is None:
        out = _sub(out, _HYP_OLD, "")
    elif rule.hyp_veto_gt != 0.65:
        out = _sub(out, _HYP_CMP_OLD, f"(t[1] or 0) > {rule.hyp_veto_gt!r} for t in traits")
    if rule.required is None:
        out = _sub(out, _REQUIRED_OLD, "                pass\n")
    if catalog.MAP_LEVELS[cfg["map"]][1] is None:
        start, end = out.index(_GATE_START), out.index(_GATE_END)
        if out.count(_GATE_START) != 1 or out.count(_GATE_END) != 1 or out[start:end].count("\n") != _GATE_LINES:
            raise ValueError("gate block markers do not delimit lines 110-132")
        out = out[:start] + out[end:]
    return out


def load_source() -> str:
    """link@405a10c from the HealDB git object database (blob c9c4aeb...)."""
    blob = subprocess.run(
        ["git", "-C", str(HEALDB_REPO), "rev-parse", f"405a10c:{LINK_PATH}"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if not blob.startswith(LINK_BLOB_PREFIX):
        raise ValueError(f"unexpected blob {blob} for {LINK_PATH}")
    raw = subprocess.run(
        ["git", "-C", str(HEALDB_REPO), "cat-file", "blob", blob], check=True, capture_output=True
    ).stdout
    return raw.decode("utf-8")


def retarget(source: str, schema: str = XVAL_SCHEMA) -> str:
    """Point the hard-coded `healdb.` table references at another schema."""
    n = source.count("healdb.hd_")
    if n == 0:
        raise ValueError("no healdb.hd_ references to retarget")
    return source.replace("healdb.hd_", f"{schema}.hd_")


def write_patched(out_dir: Path | str = XVAL_DIR, source: str | None = None, n: int = 100, seed: int = SEED) -> list[Config]:
    """One patched file `<cfg_id>.py` per sampled configuration (retargeted to healdb_xval) and configs.json."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    src = load_source() if source is None else source
    cfgs = sample_hybrids(n, seed)
    for cfg in cfgs:
        (out / f"{cfg_id(cfg)}.py").write_text(retarget(patch_link(src, cfg)), encoding="utf-8")
    entries = [{"cfg_id": cfg_id(c), "config": c.as_dict()} for c in cfgs]
    (out / "configs.json").write_text(json.dumps(entries, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return cfgs


def write_dev_meds(out_dir: Path | str = XVAL_DIR) -> tuple[int, ...]:
    """Dev medications (never test) as `dev_meds.txt` and a SQL INSERT for the `dev_meds` helper table."""
    from habench.data.splits import meds_in

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    meds = meds_in("dev")
    (out / "dev_meds.txt").write_text("".join(f"{m}\n" for m in meds), encoding="utf-8")
    values = ",".join(f"({m})" for m in meds)
    (out / "dev_meds.sql").write_text(f"INSERT INTO healdb_xval.dev_meds (id_medication) VALUES {values};\n", encoding="utf-8")
    return meds


# ---- comparison ------------------------------------------------------------------------------------------


def expected(cfg: Config, ev_dev, hier) -> list[dict]:
    return _md_like(ev_dev, hier, cfg, mapping.v1_ids, 1)


def compare_all(out_dir: Path | str = XVAL_DIR, ev_dev=None, hier=None) -> list[dict]:
    """Exact comparison of every `<cfg_id>.tsv` in `out_dir` with the core's expected `md` rows."""
    from habench.historical.replay import MD_KINDS, read_tsv
    from habench.pipeline.tables_v1 import MD_COLUMNS

    out = Path(out_dir)
    entries = json.loads((out / "configs.json").read_text(encoding="utf-8"))
    if ev_dev is None:
        from habench.data.splits import evidence_for

        ev_dev = evidence_for("dev")
    if hier is None:
        hier = mapping.load_hierarchy("v1")
    results = []
    for e in entries:
        cfg = Config.of(e["config"])
        path = out / f"{e['cfg_id']}.tsv"
        if not path.is_file():
            results.append({"cfg_id": e["cfg_id"], "config": e["config"], "status": "missing", "equal": False})
            continue
        theirs = read_tsv(path, MD_KINDS)
        ours = expected(cfg, ev_dev, hier)
        cmp = compare_rows([{c: r[c] for c in MD_COLUMNS} for r in ours], theirs, ("id_med_disease",), ())
        equal = not cmp["only_ours"] and not cmp["only_theirs"] and not cmp["differ"] and cmp["order_equal"]
        results.append({
            "cfg_id": e["cfg_id"], "config": e["config"], "status": "compared", "equal": equal,
            "n_expected": cmp["n_ours"], "n_historical": cmp["n_theirs"],
            "n_only_expected": len(cmp["only_ours"]), "n_only_historical": len(cmp["only_theirs"]),
            "n_differ": len(cmp["differ"]), "differ_sample": [[list(k), c, a, b] for k, c, a, b in cmp["differ"][:5]],
            "order_equal": cmp["order_equal"],
        })
    return results


# ---- coverage --------------------------------------------------------------------------------------------

_SQL_OK = "sim (405a10c ajustável)"


def _coverage_cell(name: str, level) -> tuple[str, str]:
    f = catalog.FACTORS[name]
    if f.stage in ("prep", "acm"):
        return "não", "contrafactual indisponível: não há resposta ACM armazenada para a entrada alterada"
    if name == "occ":
        if level == "last_upsert":
            return "fixo", "comportamento do código 405a10c; é o nível de todas as células do oráculo"
        return "não", "o código histórico só implementa o upsert com última ocorrência"
    if name == "sel":
        if level == "all":
            return "fixo", "comportamento do código 405a10c; é o nível de todas as células do oráculo"
        return "não", "o código histórico não seleciona o conceito de maior escore por entidade"
    if name in ("ent_thr", "icd_thr"):
        col = "vl_entity_score" if name == "ent_thr" else "vl_score"
        extra = "; SQL do HEAD (3 parâmetros) é oráculo possível sob o preset V2: catalogado, não executado"
        if level in (ENT_THRS if name == "ent_thr" else ICD_THRS):
            return _SQL_OK, f"constante de `{col} >= t` na linha 141{extra}"
        return "não", "nível fora da sublattice"
    if name == "trait":
        if level == "v2":
            return "não", "exige o Type da entidade, que link@405a10c não seleciona"
        return _SQL_OK, "conjuntos e regra HYPOTHETICAL nas linhas 135-148"
    if name == "map":
        if level in MAPS:
            return _SQL_OK, "bloco do portão (linhas 110-132) removido para cm_ungated; `search_repository_icd` inalterada"
        return "não", "projeção para a OMS (who_*) não existe no código histórico"
    return "não", ""


def coverage_table() -> str:
    lines = [
        "| Fator | Nível | Oráculo SQL histórico | Observação |",
        "|---|---|---|---|",
    ]
    for name, f in catalog.FACTORS.items():
        for level in f.levels:
            ok, note = _coverage_cell(name, level)
            lines.append(f"| `{name}` | `{level}` | {ok} | {note} |")
    lines.append(
        "| `patch:<id>` | `True` | não | edição semissintética: nenhuma execução histórica corresponde a ela |"
    )
    return "\n".join(lines) + "\n"


# ---- CLI -------------------------------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "prepare":
        cfgs = write_patched(XVAL_DIR)
        meds = write_dev_meds(XVAL_DIR)
        print(f"{len(cfgs)} patched sources and configs.json in {XVAL_DIR}; {len(meds)} dev medications")
        return 0
    if cmd == "compare":
        res = compare_all(XVAL_DIR)
        (XVAL_DIR / "xval_result.json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        bad = [r for r in res if not r["equal"]]
        print(f"{len(res) - len(bad)}/{len(res)} configurations equal")
        for r in bad:
            print(r["cfg_id"], r["status"], r.get("n_expected"), r.get("n_historical"), r.get("n_differ"))
        return 1 if bad else 0
    if cmd == "coverage":
        print(coverage_table(), end="")
        return 0
    print("usage: python -m habench.historical.xval {prepare|compare|coverage}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
