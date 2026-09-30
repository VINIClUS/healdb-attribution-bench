# Lead δ — provenance records, campaign harness (Study C), annotation kit (Q3)

Read `docs/tasks/00_common.md` first. Status file: `docs/status/lead-delta.md`. Branch `lead-delta`.

## Owned files (exclusive)

`src/habench/prov/**`, `src/habench/campaign/**`, `src/habench/annotation/**`, `tests/test_prov_*.py`,
`tests/test_campaign_*.py`, `tests/test_annotation_*.py`, `repro/annotation_guide.md`,
`repro/campaign_plan.template.yaml`, `docs/campanha/**`, `docs/status/lead-delta.md`.

## Inputs

Protocol §6.5, §9, §12, §13; `docs/design/desenho_inicial.md`; `docs/design/ambiente_e_comparadores.md`
(InferICD10CM contract and prices); `docs/design/mapa_codigo_healdb.md` §3 (historical translation step).

## Money rules (non-negotiable)

- Paid calls are made **only by the main session**. Your code must default to dry-run and must refuse real calls
  unless all hold: env `HAB_PAID_CALLS=1`, flag `--paid`, flag `--budget-usd <x>`, and a price entry for every
  model used. Tests never reach the network (the conftest blocks it); use `botocore.stub.Stubber` or fakes.
- Ledger `/home/vinicius/hab-data/campaign/ledger.jsonl`, cumulative across runs. Before **each attempt**, reserve
  the worst-case cost; refuse the attempt if spent + reserved would exceed the cap; reconcile after the attempt.
  Failures and retries count. Disable botocore internal retries (`max_attempts=1`) and implement retries in the
  runner with one attempt record and one reservation each.
- Worst-case costs: ACM InferICD10CM = max(1, ceil(chars/100)) units × US$0.0005 (us-east-2 price list of
  2026-09-11; keep prices in the plan file, not in code). Bedrock = (UTF-8 bytes of the prompt as an upper bound on
  input tokens) × input price + `max_tokens` × output price.

## Chunk δ1 — provenance records

`prov/`: PROV-DM-compatible records (entities, activities, agents; used, wasGeneratedBy, wasDerivedFrom,
wasAssociatedWith, wasInformedBy); every attempt has its own id (uuid4), distinct from content sha256; status,
start/end, errors, consumption, model returned, endpoint/region, dependencies; claim ledger with
`habench.types.ClaimState`; JSONL store with round-trip; export to PROV-JSON without extra dependencies; scrubbing so
credentials or auth headers can never be stored (tested).

## Chunk δ2 — campaign harness (§9, §13)

- `campaign/acm.py`: `comprehendmedical.infer_icd10_cm(Text=...)`; region parameter (us-east-2); stores the raw
  response exactly, `ModelVersion`, RequestId, HTTP date, latency, status.
- `campaign/translate.py`: Bedrock Converse API (`bedrock-runtime.converse`), model id and temperature from the
  profile, fixed `max_tokens`; historical prompt exactly `Translate to English and return only the translation: {text}`
  with the input cut at 6000 characters (HealDB `translate_leaflet_sections.py`); stores output text, usage, stop
  reason, latency.
- `campaign/schedule.py` (seeded, reproducible):
  - smoke: 20 dev texts × 5 repetitions, ACM only, input = the exact V2 `ds_text_submitted` of one representative
    medication per group (read from the V2 api_response snapshot `/home/vinicius/hab-data/snapshots/v2/`, or dumps);
  - pilot (§9.2): 60 texts from dev/cal (stratified, whole groups), three blocks — ACM isolated (fixed V2 text,
    10 executions per text), translation isolated (3 profiles × 10 executions per text, no cache), full pipeline
    (each translation → ACM text `"What this medication is indicated for:\n" + s.strip() + "\n\n"`, cut at 10,000,
    no drug-name masking) — roles per text/profile fixed before collection (6 references + 4 evaluation
    realizations, seeded); temporal blocks with randomized interleaving and null controls in every block (§9.3);
  - text selection reads `repro/split_manifest.csv` (schema in `docs/tasks/lead-alpha.md`; use a fixture in tests)
    and must refuse any `test` group (`habench.types.SealedError`).
- `campaign/runner.py`: executes a schedule with the ledger, one attempt record per call, raw outputs under
  `/home/vinicius/hab-data/campaign/<run_id>/`, resumable, stops at the cap, waits between temporal blocks.
- `campaign/estimator.py`: call counts and cost bounds; checks the §13 examples (150 × 3 × 5 = 2,250 translations;
  60 × 3 × 10 = 1,800).
- `campaign/compare.py`: level-2 comparison of repeated responses (drop only top-level `ResponseMetadata`,
  canonical JSON, array order kept) and repeated translations (exact, normalized-whitespace, edit distance).
- CLI: `uv run python -m habench.campaign {plan-smoke,plan-pilot,estimate,run,status,compare}`.
- `repro/campaign_plan.template.yaml`: region, profiles (commercial, commercial at temperature 0, open weights —
  model ids left as placeholders for the main session), `max_tokens`, prices, cap, retry policy, block spacing.
- `docs/campanha/protocolo_campanha.md` (Portuguese): how the pilot implements §9.1–9.5, roles, blocks, failure
  and retry policy, what is recorded.

## Chunk δ3 — annotation kit (§12)

`annotation/`: sampler with recorded inclusion probabilities (pilot 20 excluded from evaluation; 130 evaluation
units, 50 double + 80 single; strata by change and therapeutic coverage), blind sheet export (CSV; no system
outputs shown), agreement (percent agreement, Cohen's kappa per category, Krippendorff's alpha nominal),
adjudication merge. Tested on synthetic data only — actual sampling from test groups happens after the unseal.
`repro/annotation_guide.md` (Portuguese): CID-10 category as the main unit, subcategory only when the text
supports it, no inference from contraindications or external knowledge, reference document fixed by version.
