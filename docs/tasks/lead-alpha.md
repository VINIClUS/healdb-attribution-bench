# Lead α — data layer, pipeline core, corpus, Study A

Read `docs/tasks/00_common.md` first. Status file: `docs/status/lead-alpha.md`. Branch `lead-alpha`.

## Owned files (exclusive)

`src/habench/data/**`, `src/habench/pipeline/**`, `src/habench/historical/**`, `tests/test_data_*.py`,
`tests/test_pipeline_*.py`, `tests/test_historical_*.py`, `scripts/replay/**`, `repro/sources_manifest.json`,
`repro/replay_manifest.json`, `repro/corpus_groups.csv`, `repro/split_manifest.csv`, `repro/claims_study_a.yaml`,
`docs/estudo_a/**`, `docs/status/lead-alpha.md`.

## Inputs

- Design: `docs/design/desenho_inicial.md` §A (layout, signatures), §B1–B2 (factors, hybrid semantics), §E (tests);
  `docs/design/mapa_codigo_healdb.md` (exact V1/V2 code semantics with line numbers);
  `docs/design/inventario_workspace.md` (dump paths, `dumprows.py` API, replay scripts, samples).
- Historical code (read-only): V1 = `git -C /home/vinicius/code/HealDB show 405a10c:src/nlp_extraction/<file>`
  (also archived in `/home/vinicius/healdb-reconstrucao/code/405a10c/`); V2 = `/home/vinicius/code/HealDB/src/nlp_extraction/`.
- Workspace scripts to port (clean-room, never import them): `/home/vinicius/healdb-reconstrucao/scripts/{dumprows.py,
  acm_text_v1.py, extend_analysis.py, replay_*.sh, replay_driver.py, replay_compare.py, extend_from_link_405a10c.patch}`.
- Reports F1/F2 (`/home/vinicius/code/HealDB/doc/`) give the reference numbers.

## Chunk α1 — data layer

- `data/dumps.py`: streaming mysqldump reader with the `columns/rows/records` API of `dumprows.py`; keep numeric
  text exact where fidelity needs it (store floats as Python `float` parsed from the dump text, which reproduces
  V1 exactly; the 1-ULP difference appears only after a MySQL reload).
- `data/store.py`: Parquet snapshots under `/home/vinicius/hab-data/snapshots/{v1,v2,g0327}/<table>.parquet` with a
  `manifest.json` (source file sha256, row count, snapshot sha256). Raw ACM JSON strings are kept byte-exact, plus a
  per-row sha256. Tables: api_response, translate_eng_leaflet_section, medication, icd_group/category/subcategory,
  V1 entity/trait/medication_disease/medication_disease_extend, V2 entity_icd/entity_trait/cutoff_audit/medication_disease,
  0327 api_response.
- Tests (`-m dumps`): row counts equal F2's matrix (e.g. api_response 7,447 per run; entity 274,010; trait 469,957;
  md 43,194; extend 44,233; entity_icd 375,595; entity_trait 107,543; cutoff_audit 75,119; V2 md 27,861).

## Chunk α2 — pipeline core **[Opus: core semantics]**

- `pipeline/{catalog,evidence,core,trace,mapping,semantics,equality}.py` per design §A/§B1/§B2: one parameterized,
  deterministic function over the parsed JSON (array order preserved, never sorted) with presets `V1` and `V2`;
  factor catalog (`occ`, `sel`, `ent_thr`, `icd_thr`, `trait`, `map`, `patch:<id>`; pre-ACM factors catalogued as
  unavailable without a stored response); per-stage trace (candidates, per-filter decisions with reasons, discards);
  `equality.py` with the three levels of §5.2 — level 2 drops exactly the top-level `ResponseMetadata` object and
  nothing else, compares canonical JSON preserving array order.
- `pipeline/tables_v1.py`, `tables_v2.py`: materialize the historical tables from responses.
- **GATE 1 (tests `-m dumps`, exact):** V1 `entity` 274,010 and `trait` 469,957 rows equal to the dump (all columns);
  md 43,194 rows equal including ids 1..43,194; the funnel 274,010 → 265,587 → 259,198 → 171,713 → 43,194 → 43,194;
  `extend` 44,233 rows equal with ids 23,302..67,534 (label: inferred rule, F1 §2.4). Performance: full V1 run ≤ 60 s;
  64 hybrids of the V1→V2 bundle over the corpus ≤ 120 s.
- Secondary, time-boxed (≤ 1 h of effort): V2 `entity_icd`, `entity_trait`, `cutoff_audit` exact and md presence
  27,861; md attributes with an explicit tie policy. If it fails, document and move on.
- When GATE 1 passes: commit, write `GATE1: passed` with the exact test lines at the top of your status file, and
  continue with α3 (the main session merges asynchronously).

## Chunk α3 — corpus, strata, splits

- `data/groups.py`: document groups = union-find over (identical normalized PT indication: NFC, strip, collapse
  whitespace, casefold) ∪ (near-duplicate PT: word 5-shingle Jaccard ≥ 0.90, threshold fixed now, not tuned) ∪
  (identical stripped EN indication). No leaflet is shared across medications. Report the largest component; if one
  component exceeds 1% of medications, report it (do not tune the threshold on outcomes).
- Eligible universe: the 7,447 medications with a V1 ACM response. Strata (§4.4): EN length bin, entity presence,
  trait occurrence, candidate multiplicity, threshold proximity (any score in [0.55, 0.70)), fallback need,
  >10k-char V1 text, empty response, V1 phase (from the HTTP date).
- `data/splits.py`, `data/sampling.py`: seed 20260930; about 1,000 distinct texts (groups): dev ≈ 200 + every
  individually inspected medication (all of `/home/vinicius/healdb-reconstrucao/out/extend_amostra.csv`; ids cited in F1:
  4, 7, 560, 3205, 4139, 298, 1093, 2188, 2201, 3297, 3298, 3300, 3302, 3819, 3866, 4098, 4825, 7294, 7683, 8763, 8764,
  10036, 10331), cal ≈ 200, test ≈ 600, remaining groups `reserve`. Whole groups only; record inclusion
  probabilities. Any function that would load evidence for `test` groups raises `habench.types.SealedError`.
- Outputs: `repro/corpus_groups.csv` (`group_id,medication,pt_sha256,en_sha256,link`) and `repro/split_manifest.csv`
  (`group_id,partition,medications,n_medications,stratum,inclusion_prob`; `medications` semicolon-separated;
  `group_id` = `g` + first 12 hex of sha256 of the sorted medication ids). Record effective sizes in status.

## Chunk α4 — Study A (P0)

- `repro/sources_manifest.json`: REDU files (DOI `10.25824/redu/24I1FH`, file ids, md5 from
  `/home/vinicius/healdb-reconstrucao/out/redu_versions.json` recomputed on `/home/vinicius/healdb-reconstrucao/src/redu/`),
  sha256 of each dump `.sql` used, git blob ids of the historical scripts, F1/F2/F3 hashes
  (`docs/protocolo/SHA256SUMS`).
- `scripts/replay/`: Docker replay of 405a10c adapted from the workspace scripts: containers and volumes named
  `healdb-replay-*`, password from `HAB_MYSQL_PASSWORD`, never copied from any script. Plus a hybrid
  cross-validation: patch the constants of `link@405a10c` (thresholds, trait sets, HYPOTHETICAL rule, gate) for
  ~100 sampled hybrids on **dev medications only**, compare with the core, and publish a coverage table of which
  factor cells have a historical SQL oracle. You cannot run Docker: when the scripts are ready, write
  `READY_FOR_DOCKER: <exact commands>` in your status file and continue with the rest. After the main session runs
  them (you will be resumed), write `repro/replay_manifest.json` from the logs.
- `historical/`: re-derive in committed code, reported by phase, with exactly what was compared:
  (a) ACM repeatability at level-2 equality among identical submitted texts inside one run (V1 reconstructed text
  per F1 §4.2, V1 phases 1/2/3; V2 `ds_text_submitted`, phases A/B; 2024 raw EN), with exact one-sided 95% upper
  bounds; (b) translation variability (identical PT → distinct EN: counts, character edit distances);
  (c) the real contrast "V1 post-processing → V2 post-processing" on the same V1 responses (bundle `V1_TO_V2`),
  with family-shape counts reported **separately for dev+cal and for the full corpus** (the full-corpus figure is
  descriptive only, see deviation D2).
- `repro/claims_study_a.yaml`: each §1.1 premise and the key F1/F2 claims with a state
  (`armazenado | rederivado_verificado | inferido_compativel | refutado | nao_determinado`) and evidence pointers.
- `docs/estudo_a/relatorio_estudo_a.md` (Portuguese): descriptive Study A report; no causal claims about V1→V2.
