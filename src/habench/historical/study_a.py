"""Study A re-derivations: `uv run python -m habench.historical.study_a` writes docs/estudo_a/resultados_estudo_a.json.

Aggregates only. Full-corpus figures include the sealed test partition's medications as counts and are
descriptive (deviation D2); no per-association or per-medication output is written.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from habench.historical import contrast, repeatability, translation

OUT_PATH = Path(__file__).parents[3] / "docs" / "estudo_a" / "resultados_estudo_a.json"

INPUT_STATES = {
    "v1_api_response": "armazenado",
    "v2_api_response": "armazenado",
    "g0327_api_response": "armazenado",
    "v2_text_submitted": "armazenado",
    "v1_submitted_text": "inferido_compativel",
    "g0327_submitted_text": "inferido_compativel",
    "translation_texts": "armazenado",
    "contrast_v1_to_v2_hybrids": "rederivado (hybrids other than the V1 and V2 presets have no historical oracle)",
}


def _provenance() -> dict:
    from habench.data import splits, store

    tables = {
        "v1": ("hd_int_med_disease_api_response", "hd_translate_eng_leaflet_section", "hd_icd_category",
               "hd_icd_subcategory"),
        "v2": ("hd_int_med_disease_api_response",),
        "g0327": ("hd_int_med_disease_api_response", "hd_translate_eng_leaflet_section"),
    }
    return {
        snap: {t: store.manifest(snap)[t]["snapshot_sha256"] for t in ts} for snap, ts in tables.items()
    } | {"split_manifest_csv": f"{splits.MANIFEST_PATH.name} (partition labels only)"}


def compute() -> dict:
    return {
        "scope_note": (
            "Descriptive aggregates. Repeatability and translation cover the full corpus and the contrast is "
            "reported for dev+cal and, descriptively only, for the full corpus (deviation D2). No causal claim "
            "about the V1 to V2 transition (protocol 3, Study A)."
        ),
        "input_claim_states": INPUT_STATES,
        "snapshot_sha256": _provenance(),
        "a_repeatability": repeatability.compute(),
        "b_translation": translation.compute(),
        "c_contrast_v1_to_v2": contrast.compute(),
    }


def render(result: dict) -> str:
    return json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def summary(result: dict) -> str:
    lines = []
    for run, r in result["a_repeatability"].items():
        o = r["overall"]
        lines.append(
            f"(a) {run}: groups {o['n_texts_with_repeats']}, meds {o['n_meds_in_groups']}, pairs {o['n_pairs']}, "
            f"differing groups {o['n_groups_differing']}, differing pairs {o['n_pairs_differing']}, "
            f"upper95 {o['upper95_differing_group_fraction']}, versions {r['model_versions']}"
        )
    for key, block in result["b_translation"].items():
        if isinstance(block, dict) and "full_corpus" in block:
            f = block["full_corpus"]
            lines.append(
                f"(b) {key}: groups {f['n_groups_with_repeats']}, with distinct EN {f['n_groups_with_distinct_english']}, "
                f"abs dist {f['distance_absolute']}"
            )
    for scope, c in result["c_contrast_v1_to_v2"].items():
        lines.append(
            f"(c) {scope}: keys V1 {c['n_keys_v1']}, appear {c['appear']}, disappear {c['disappear']}, "
            f"shapes {c['shape_histogram']}, participation {c['participation']}, non-monotone {c['non_monotone']}, "
            f"distinct tables (changed) {c['distinct_truth_tables_changed']}"
        )
    return "\n".join(lines)


def main() -> int:
    t0 = time.time()
    result = compute()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(render(result), encoding="utf-8")
    print(summary(result))
    print(f"wrote {OUT_PATH} in {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
