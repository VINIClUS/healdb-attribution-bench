"""Study A (a): ACM repeatability inside one run, at level-2 equality, among identical submitted texts.

Level 2 (`habench.pipeline.equality.level2_digest`): the parsed response without the top-level
`ResponseMetadata`, canonical JSON with sorted object keys; arrays keep their order. Two responses are
"equal" iff their level-2 digests are equal. A medication with a missing, NULL or undecodable response is
excluded (never treated as a different answer).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping
from itertools import combinations

from habench.data.sampling import assign_phases, response_date
from habench.pipeline.equality import canonical_json, extraction_content, level2_digest

V1_HEADER_1 = "What this medication is indicated for:\n"
V1_HEADER_2 = "\n\nHow this medication works:\n"
V1_LIMIT = 10_000

COMPARED = (
    "level-2 equality: response JSON without the top-level ResponseMetadata key, canonical serialization "
    "(sorted object keys, arrays in their original order), so ModelVersion, entities, traits, candidates and "
    "scores all count; RequestId and HTTP date do not. Groups are sets of >= 2 medications of one run with "
    "identical submitted text."
)


def v1_text(indication_eng: str) -> str:
    """V1 submitted text reconstructed per F1 4.2 (not stored): (P + s + M + s)[:10000], s = stripped English."""
    s = indication_eng.strip()
    return (V1_HEADER_1 + s + V1_HEADER_2 + s)[:V1_LIMIT]


def clopper_pearson_upper(k: int, n: int, confidence: float = 0.95) -> float:
    """Exact one-sided upper confidence bound for a binomial proportion (k successes of n)."""
    if not 0 <= k <= n or n < 1:
        raise ValueError("need 0 <= k <= n and n >= 1")
    if k == n:
        return 1.0
    alpha = 1.0 - confidence
    if k == 0:
        return 1.0 - alpha ** (1.0 / n)

    def cdf(p: float) -> float:  # P(X <= k), X ~ Binomial(n, p), summed in log space
        logs = [
            math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * math.log(p) + (n - i) * math.log1p(-p)
            for i in range(k + 1)
        ]
        top = max(logs)
        return math.exp(top) * sum(math.exp(x - top) for x in logs)

    lo, hi = k / n, 1.0  # cdf decreases in p: cdf(k/n) > alpha > cdf(1-)
    for _ in range(200):
        mid = (lo + hi) / 2
        if cdf(mid) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def phase_labels(run: str, phases: Mapping[int, int]) -> dict[int, str]:
    """V2 phases are lettered A, B, ...; V1 and 2024 phases are numbered; phase 0 (no date) is `none`."""
    def label(p: int) -> str:
        if p == 0:
            return "none"
        return chr(ord("A") + p - 1) if run == "v2" else str(p)

    return {m: label(p) for m, p in phases.items()}


def attributes_unordered_digest(raw: str) -> str:
    """Level-2 digest after sorting each entity's Attributes by canonical JSON (a diagnosis, not a level)."""
    doc = extraction_content(raw)
    for ent in doc.get("Entities") or []:  # type: ignore[union-attr]
        if ent.get("Attributes"):
            ent["Attributes"] = sorted(ent["Attributes"], key=canonical_json)
    return hashlib.sha256(canonical_json(doc).encode()).hexdigest()


def _block(groups: list[tuple[int, ...]], differs: Mapping[tuple[int, ...], bool], pairs_diff: int) -> dict:
    n = len(groups)
    k = sum(1 for g in groups if differs[g])
    return {
        "n_texts_with_repeats": n,
        "n_meds_in_groups": sum(len(g) for g in groups),
        "n_pairs": sum(len(g) * (len(g) - 1) // 2 for g in groups),
        "n_groups_differing": k,
        "n_pairs_differing": pairs_diff,
        "differing_group_fraction": (k / n) if n else None,
        "upper95_differing_group_fraction": clopper_pearson_upper(k, n) if n else None,
    }


def analyze_run(
    run: str,
    texts: Mapping[int, str | None],
    responses: Mapping[int, str | None],
    text_state: str,
    text_definition: str,
) -> dict:
    """Repeatability of one run. `texts`: submitted text per medication; `responses`: raw ds_api_response."""
    phase_of = phase_labels(run, assign_phases({m: response_date(r) for m, r in responses.items()}))
    digest: dict[int, str] = {}
    failed = 0
    for m, raw in responses.items():
        if raw is None:
            failed += 1
            continue
        try:
            digest[m] = level2_digest(raw)
        except ValueError:  # json.JSONDecodeError is a ValueError
            failed += 1
    by_text: dict[str, list[int]] = defaultdict(list)
    no_text = 0
    for m in sorted(digest):
        t = texts.get(m)
        if t is None:
            no_text += 1
            continue
        by_text[t].append(m)
    groups = [tuple(v) for v in by_text.values() if len(v) >= 2]
    differs = {g: len({digest[m] for m in g}) > 1 for g in groups}
    # auxiliary diagnosis only (level 2 keeps array order): differing groups equal once each entity's
    # Attributes list is put in a canonical order
    attr_order_only = sum(
        1 for g in groups if differs[g] and len({attributes_unordered_digest(responses[m]) for m in g}) == 1
    )

    model_versions: Counter[str] = Counter()
    for m, raw in responses.items():
        if m in digest:
            model_versions[str(json.loads(raw).get("ModelVersion"))] += 1  # type: ignore[arg-type]

    pair_stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    per_group_pairs_diff: dict[tuple[int, ...], int] = {}
    for g in groups:
        nd = 0
        for a, b in combinations(g, 2):
            key = "-".join(sorted((phase_of[a], phase_of[b])))
            pair_stats[key][0] += 1
            if digest[a] != digest[b]:
                pair_stats[key][1] += 1
                nd += 1
        per_group_pairs_diff[g] = nd

    def subset(sel) -> dict:
        gs = [g for g in groups if sel(g)]
        return _block(gs, differs, sum(per_group_pairs_diff[g] for g in gs))

    labels = sorted(set(phase_of.values()))
    return {
        "run": run,
        "text_state": text_state,
        "text_definition": text_definition,
        "compared": COMPARED,
        "n_responses": len(responses),
        "n_responses_excluded_failed": failed,
        "n_excluded_without_text": no_text,
        "model_versions": dict(sorted(model_versions.items())),
        "phase_sizes": dict(sorted(Counter(phase_of.values()).items())),
        "overall": subset(lambda g: True),
        "differing_groups_attribute_order_only": attr_order_only,
        "by_phase_all_members_in_phase": {
            p: subset(lambda g, p=p: {phase_of[m] for m in g} == {p}) for p in labels
        },
        "cross_phase": subset(lambda g: len({phase_of[m] for m in g}) > 1),
        "pairs_by_phase_pair": {k: {"n_pairs": v[0], "n_pairs_differing": v[1]} for k, v in sorted(pair_stats.items())},
    }


def _load(snap: str, table: str, columns: list[str]) -> dict[str, list]:
    from habench.data.store import load_table

    tab = load_table(snap, table, columns)
    return {c: tab.column(c).to_pylist() for c in columns}


def _responses(snap: str) -> dict[int, str | None]:
    d = _load(snap, "hd_int_med_disease_api_response", ["id_medication", "ds_api_response"])
    return {int(i): r for i, r in zip(d["id_medication"], d["ds_api_response"])}


def _english(snap: str) -> dict[int, str | None]:
    d = _load(snap, "hd_translate_eng_leaflet_section", ["id_medication", "ds_indication_eng"])
    return {int(i): t for i, t in zip(d["id_medication"], d["ds_indication_eng"])}


def compute() -> dict:
    v1_en = _english("v1")
    v1_texts = {m: (None if t is None else v1_text(t)) for m, t in v1_en.items()}
    d2 = _load("v2", "hd_int_med_disease_api_response", ["id_medication", "ds_text_submitted", "ds_api_response"])
    v2_texts = {int(i): t for i, t in zip(d2["id_medication"], d2["ds_text_submitted"])}
    v2_resp = {int(i): r for i, r in zip(d2["id_medication"], d2["ds_api_response"])}
    return {
        "v1": analyze_run(
            "v1", v1_texts, _responses("v1"), "inferido_compativel",
            "(header1 + s + header2 + s)[:10000], s = ds_indication_eng.strip() (F1 4.2); reconstruction, not stored",
        ),
        "v2": analyze_run(
            "v2", v2_texts, v2_resp, "armazenado", "ds_text_submitted of hd_int_med_disease_api_response, as stored",
        ),
        "g0327": analyze_run(
            "g0327", _english("g0327"), _responses("g0327"), "inferido_compativel",
            "raw ds_indication_eng of the g0327 translate table, no strip, no header (F1 C0); inferred, not stored",
        ),
    }
