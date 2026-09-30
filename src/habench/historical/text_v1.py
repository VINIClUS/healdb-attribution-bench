"""Text submitted to ACM in V1: reconstruction checked against the stored offsets (F1 §4.2-4.7).

V1 did not store the submitted text. The reconstruction (P + s + "\\n\\n" + H + s)[:10000], with
s = ds_indication_eng.strip(), is checked span by span: for every entity and attribute,
text[BeginOffset:EndOffset] == Text in code points. Spans cover only part of the characters, so a
full match makes the reconstruction compatible with the evidence (`inferido_compativel`), not
proven identical. The V2 stored `ds_text_submitted` is the method control.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterable, Mapping
from email.utils import parsedate_to_datetime
from pathlib import Path

P = "What this medication is indicated for:\n"
SEP = "\n\n"
H = "How this medication works:\n"
LIMIT = 10_000
PHASE_GAP_SECONDS = 3600
OUT_PATH = Path(__file__).parents[3] / "docs" / "estudo_a" / "texto_v1.json"


def v1_text(en: str) -> str:
    s = en.strip()
    return (P + s + SEP + H + s)[:LIMIT]


def indication_only(en: str) -> str:
    return (P + en.strip() + SEP)[:LIMIT]


def raw_text(en: str) -> str:
    return en


HYPOTHESES: dict[str, Callable[[str], str]] = {
    "v1_reconstructed": v1_text,  # 405a10c code with the duplicated indication
    "raw_indication": raw_text,  # 0e43ed9 code: raw ds_indication_eng
    "indication_only": indication_only,  # header + indication once (V2 layout without the regex)
}


def spans(doc: dict) -> list[tuple[str, int, int, str]]:
    out = []
    for e in doc.get("Entities") or []:
        out.append(("E", e["BeginOffset"], e["EndOffset"], e["Text"]))
        out += [("A", a["BeginOffset"], a["EndOffset"], a["Text"]) for a in e.get("Attributes") or []]
    return out


def covered(sp: Iterable[tuple[str, int, int, str]]) -> int:
    n = cur = 0
    for b, e in sorted((b, e) for _, b, e, _ in sp):
        b = max(b, cur)
        if e > b:
            n, cur = n + e - b, e
    return n


def check_texts(docs: Mapping[int, dict], texts: Mapping[int, str]) -> dict:
    """Span agreement of candidate `texts` with the responses (only responses with entities count)."""
    n_resp = n_all_ok = n_spans = n_ok = chars = total = 0
    failing: list[int] = []
    for med in sorted(docs):
        sp = spans(docs[med])
        if not sp:
            continue
        t = texts[med]
        ok = sum(t[b:e] == x for _, b, e, x in sp)
        n_resp += 1
        n_spans += len(sp)
        n_ok += ok
        if ok == len(sp):
            n_all_ok += 1
        else:
            failing.append(med)
        chars += covered(sp)
        total += len(t)
    return {
        "responses_with_entities": n_resp,
        "responses_all_spans_ok": n_all_ok,
        "spans": n_spans,
        "spans_ok": n_ok,
        "chars_covered": chars,
        "chars_total": total,
        "frac_covered": round(chars / total, 6) if total else None,
        "failing_examples": failing[:10],
    }


def http_date(doc: dict):
    return parsedate_to_datetime(doc["ResponseMetadata"]["HTTPHeaders"]["date"])


def phases(docs: Mapping[int, dict], label: Callable[[int], str]) -> list[dict]:
    """Groups of responses separated by gaps > 1 h between consecutive HTTP dates."""
    items = sorted((http_date(d), m) for m, d in docs.items())
    groups: list[list[tuple]] = [[items[0]]]
    for a, b in zip(items, items[1:]):
        if (b[0] - a[0]).total_seconds() > PHASE_GAP_SECONDS:
            groups.append([])
        groups[-1].append(b)
    out = []
    for k, g in enumerate(groups, 1):
        ids = sorted(m for _, m in g)
        out.append({
            "phase": label(k),
            "n": len(g),
            "start_utc": g[0][0].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_utc": g[-1][0].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ids": ids if len(ids) <= 30 else None,
        })
    return out


def _load(snap: str) -> tuple[dict[int, dict], dict[int, dict]]:
    from habench.data.store import load_records

    docs = {r["id_medication"]: json.loads(r["ds_api_response"])
            for r in load_records(snap, "hd_int_med_disease_api_response")}
    rows = load_records(snap, "hd_translate_eng_leaflet_section")
    return docs, {r["id_medication"]: r for r in rows}


def study() -> dict:
    from habench.data.store import load_records
    from habench.pipeline.mapping import load_hierarchy, nodot

    v1_docs, v1_tr = _load("v1")
    en = {m: v1_tr[m]["ds_indication_eng"] or "" for m in v1_docs}
    v1_checks = {name: check_texts(v1_docs, {m: f(en[m]) for m in v1_docs}) for name, f in HYPOTHESES.items()}
    long_texts = sorted(m for m in v1_docs if len(P + en[m].strip() + SEP + H + en[m].strip()) > LIMIT)

    v2 = load_records("v2", "hd_int_med_disease_api_response")
    v2_docs = {r["id_medication"]: json.loads(r["ds_api_response"]) for r in v2}
    submitted = {r["id_medication"]: r["ds_text_submitted"] for r in v2}
    v2_check = check_texts(v2_docs, submitted)
    v2_equal_v1 = sum(submitted[m] == v1_text(en[m]) for m in v2_docs if m in en)

    g_docs, g_tr = _load("g0327")
    g_en = {m: g_tr[m]["ds_indication_eng"] or "" for m in g_tr}
    same_tr = sorted(m for m in v1_tr if m in g_en and (v1_tr[m]["ds_indication_eng"] or "") == g_en[m])
    diff_tr = sorted(m for m in v1_tr if m in g_en and (v1_tr[m]["ds_indication_eng"] or "") != g_en[m])
    run2024_vs_current = check_texts(g_docs, {m: raw_text(en.get(m, "")) for m in g_docs})
    run2024_vs_0327 = check_texts(g_docs, {m: raw_text(g_en.get(m, "")) for m in g_docs})

    h = load_hierarchy("v1")
    md = load_records("v1", "hd_medication_disease", ["cd_icd_full"])
    dotted = sum("." in r["cd_icd_full"] for r in md)
    in_hier = sum(nodot(r["cd_icd_full"]) in h.cat or nodot(r["cd_icd_full"]) in h.subcat for r in md)

    return {
        "compared": "text[BeginOffset:EndOffset] == Text in code points, entities and attributes; "
                    "only responses with entities are counted; coverage = union of span intervals / text length",
        "v1": {
            "text_state": "inferido_compativel",
            "hypotheses": v1_checks,
            "responses_without_entities": sum(1 for d in v1_docs.values() if not spans(d)),
            "texts_over_10000_chars": {"n": len(long_texts), "ids": long_texts},
            "model_versions": _count(d.get("ModelVersion") for d in v1_docs.values()),
            "phases": phases(v1_docs, str),
        },
        "v2": {
            "text_state": "armazenado",
            "ds_text_submitted_check": v2_check,
            "responses_without_entities": sum(1 for d in v2_docs.values() if not spans(d)),
            "submitted_equal_to_v1_reconstruction": v2_equal_v1,
            "model_versions": _count(d.get("ModelVersion") for d in v2_docs.values()),
            "phases": phases(v2_docs, lambda k: chr(64 + k)),
        },
        "run_2024": {
            "model_versions": _count(d.get("ModelVersion") for d in g_docs.values()),
            "phases": phases(g_docs, str),
            "raw_current_translation_check": run2024_vs_current,
            "raw_0327_translation_check": run2024_vs_0327,
        },
        "translation_0327_vs_v1": {"identical": len(same_tr), "different": len(diff_tr), "different_ids": diff_tr},
        "v1_md_code_system": {"rows": len(md), "dotted": dotted, "nodot_exact_in_hierarchy": in_hier},
    }


def _count(xs: Iterable) -> dict:
    out: dict = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items()))


def main(argv: list[str]) -> int:
    res = study()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(res, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    v = res["v1"]["hypotheses"]["v1_reconstructed"]
    print(f"V1 reconstructed: {v['responses_all_spans_ok']}/{v['responses_with_entities']} responses, "
          f"{v['spans_ok']}/{v['spans']} spans, coverage {v['frac_covered']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
