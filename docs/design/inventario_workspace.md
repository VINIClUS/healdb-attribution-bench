# Inventário do workspace ~/healdb-reconstrucao

> Relatório de subagente (Sonnet) produzido em 2026-09-30 na sessão de planejamento, somente leitura.
> Números aqui são de rascunho: re-derivar em código versionado antes de citar em relatório.
> Onde se lê ThesisBench/thesisbench, leia healdb-attribution-bench/habench.

All read-only; Python ran with `-B`. `W` = `/home/vinicius/healdb-reconstrucao` (scripts 252 KB, out 6.5 MB, code 14 MB, src 441 MB, x 4.2 GB).

## 0. Findings that matter for a benchmark
- **Three independent ACM runs** cover the same 7,447 medications, with no shared RequestIds:
  - 2024-06-15, model 2.7.0.20231001 (0327 dump and git CSV; text was the raw `ds_indication_eng`).
  - V1, 2025-05-29, model 3.0.0.20231001.
  - V2, 2025-12-31 to 2026-01-04, model 3.2.0.20251001. The text is stored in `ds_text_submitted`. 3,367 texts carry `<drug>` masking; phase A has 7,016 rows and phase B 431.
- **V1 text is a doubled indication.** It is `(P + s + "\n\n" + H + s)[:10000]` with `s = ds_indication_eng.strip()`.
  - All 235,557 spans (150,506 entities, 85,051 attributes) satisfy `text[b:e]==Text` by code point. Only 12 would match as UTF-8 byte offsets.
  - 7,189 responses have entities and 258 have none. 20 candidates exceeded 10k characters and were cut.
  - No span touches P, the separator or H. The offsets prove `s` and the lengths, not the header wording. CRLF, two-space and lowercase-H variants also score 7,189/7,189, so the header comes from the code at 405a10c.
  - Each span sits in copy 1 (118,871) or copy 2 (116,686). Using the responses as gold would duplicate entities.
- `hd_translate_eng_leaflet_section` is byte-identical in V1 and V2. The 0327 dump differs only for ids 3205 and 4139.

## 1. scripts/ (`W/scripts/`)
**Importable** (put `scripts/` on `sys.path`; `BASE` is hardcoded to `~/healdb-reconstrucao/x`):

- **`sources.py`**
  - `BASE`, `SOURCES` (keys C0605, O0605, O0605s, V1, V1s, V2, V2s, K26c, K26o).
  - `files(label)->{fname:path}`, `table_of(fname)`.
- **`dumprows.py`** streams a mysqldump `.sql` without MySQL:
  ```
  path(label, table)->str                          # BASE/SOURCES.get(label,label)/healdb_<table>.sql
  columns(label, table, file=None)->list[str]      # CREATE TABLE order
  rows(label, table, file=None)->Iterator[list]    # values: None|int|float|str
  records(label, table, file=None)->Iterator[dict]
  ```
  - `label` is a SOURCES key or a directory relative to `BASE`. `file=` overrides the path (used for 0327).
  - NULL becomes None; integers become int; anything with `.` or `e` becomes float, so DECIMAL loses exactness.
  - DATE, JSON and LONGBLOB come back as str. JSON needs `json.loads`; blobs are utf-8 decoded with surrogateescape.
  - It is line-based, one `INSERT..VALUES (..),(..);` per line. It has no `0x` or `b''` literal support (raises ValueError).
  - Measured speed: V1 api_response (157 MB) in 10.5 s, V2 (85 MB) in 7.3 s, leaflet (240 MB) in about 6 s, at 42 MB RSS.
- **`acm_text_v1.py`**
  - Constants: `P` (39 chars), `SEP="\n\n"`, `H` (27 chars), `LIM=10000`.
  - Reconstruction: `T(a, b, sep=SEP, h=H)=(P+a+sep+h+b)[:LIM]`, so V1 is `T(s, s)`. Also `bloco(x)=(P+x.strip()+SEP)[:LIM]` and `candidatos(raw, func, nome)->dict` (16 hypotheses).
  - Offset check:
    - `spans(resp)->[('E'|'A',Begin,End,Text)]`
    - `n_ok(texto, sp)->int`
    - `geometria(sp, ls, lc)` (copy 1 is [39, 39+ls); copy 2 starts at 39+ls+2+27)
  - Helpers:
    - `union`
    - `dist(xs, ps)`
    - `Cont` (Counter with `.add(ok,n)` and `.out()`)
    - `fases`
    - `http_date`
    - `iso`
    - `troca_nome`
    - `troca_wow`
    - `v2_regex(raw, nome)`
  - Drivers: `analisa_v1(tr, med)`, `analisa_v2(tr, med, rids_v1)`, `geracao_2024(...)`, `main()`.
  - `geracao_2024` reads the git blob `405a10c:data/output/interoperability/export_hd_int_med_disease_api_response.csv` from `~/code/HealDB`.
  - Outputs: `out/acm_text_v1_por_resposta.csv`, `out/acm_text_v1_resumo.json`.
- **`extend_analysis.py`** is a top-level script (94 s, 503 MB) that writes `out/extend_*`.
  - `carrega()` fills module globals:
    - `cat{cd_cat:(id_cat,id_group)}` and `sub{cd_subcat:(id_subcat,id_cat)}` from the ICD tables, plus `gcat`
    - `ent[(med,code,vl_score,vl_entity_score)]` from V1 entity, by position `r[0],r[1],r[3],r[5]`
    - `tr[(med,code)]=[(nm_trait,score)]`, `md`, `ex`
  - `avalia()->flags` per entity row applies these tests:
    - hierarchy gate: code without dot is in category, in subcategory, or its first 3 characters are in category
    - excluded traits: LOW_CONFIDENCE, NEGATION, PERTAINS_TO_FAMILY
    - HYPOTHETICAL with score above 0.65
    - both scores at least 0.6
    - valid trait: DIAGNOSIS, SYMPTOM, SIGN, or HYPOTHETICAL at 0.6 or below
  - Other functions: `main_trait(t)`, `funis(flags)`, `hier_md`, `hier_ext_a`, `hier_ext_b` (each `(nd)`), `rule_rows(flags, gate, hier)`, `acerto(rows, real, id_base)`, `reimplementa`, `estrita`, `particao(kex)`, `verifica(F,P)`.
  - Funnel for md: 274,010 → 265,587 → 259,198 → 171,713 → 43,194. Extend without the gate: 267,392 → 177,839 → 44,233.
  - **44 of its 47 built-in checks pass.** The failures:
    - hierarchy A reaches only 9 of 10 columns; `hier_ext_b` is the rule that reproduces the data.
    - "fora do top-5, offsets mapeados" gives 814 and 17 against the expected 347 and 484. The raw-offset variant matches.
  - Porting needs a refactor (globals, positional column indexes).
- **Replay** (images `mysql:8.0.33`, `python:3.12-slim`)
  - `replay_up.sh`
    - Runs container `healdb-replay-mysql` with volume `healdb-replay-mysql-data`, `x/` mounted read-only, and a hardcoded local root password.
    - Schema `healdb` holds all of V1. Schema `v1` holds untouched entity, trait, md and extend. Schema `v2` holds the V2 api_response.
    - Table loads take about 54 s in total, plus MySQL init.
  - `replay_405a10c.sh`
    - Runs `git archive 405a10c main.py db_utils.py src` into `code/405a10c` and checks 3 blob hashes.
    - Starts `healdb-replay-py` (python:3.12-slim) on the MySQL container's network, with no AWS variables. It installs mysql-connector-python 26.7.0 and SQLAlchemy 2.1.1, then runs `replay_driver.py`.
    - The driver calls the unmodified `process_disease_data_json(cnx,cursor)` (546 s), then does an operator `TRUNCATE hd_medication_disease` that is not in the code, then `link_medications_with_diseases` (148 s). Total 695 s.
  - `replay_extend.sh`
    - Applies `extend_from_link_405a10c.patch` to link@405a10c. Change #4 in that patch was inferred from V1 data, not predicted.
    - Does `TRUNCATE` plus `AUTO_INCREMENT=23302`, a value fitted to the data. Takes 58.6 s and gives 44,233 rows with ids 23302 to 67534.
    - So extend is fitted, not independent.
  - `replay_compare.py` compares `healdb` with `v1` by fingerprint, EXCEPT and natural key.
    - Trait (469,957 rows), md (43,194 rows, ids equal) and extend are identical.
    - Entity (274,010 rows) has one differing float: med 560, C49.9, `vl_score` ends in ...998 versus ...995. Compare floats with a tolerance.
    - The log ends "HÁ DIFERENÇAS".
  - Docker now: the three images are cached, but no `healdb-*` containers or volumes remain. A rebuild takes about 13 min.
- **Other scripts** (mostly run-at-import, not libraries):
  - `inventory.py` writes md5s to `inventario_sql.csv`.
  - `parse_ddl.py`: `parse(path)`, `diff(a,b)`, `load_all()`.
  - `matriz.py` writes `matriz.csv` and markdown tables.
  - `data_compare.py`, `load.sh`, `mysql_up.sh` use the older container `healdb-recon-mysql`.
  - `code_scan.py`, `compare0327.py`, `geracao2024.py`.
  - `dump0327.sh` (7z via crazymax/7zip).
  - `nlp_timeline.sh`, `doc_evidencias.sh` (git-history evidence).
  - `v2_backspace_check.py`, `extend_amostra.py` (seed 20260929, 250 rows), `xlsx_diff.py`.
  - `extend_from_link_405a10c.patch`, `relatorio_template.md`.
  - `prehist_nested.sh` exists (not opened).

## 2. x/ (`W/x/`)
- **Base directories**
  - V1: `v1_dump_0711/Dump20250711_Dump_and_Structure/` (582 MB, 33 files).
  - V2: `v2_dump_0828/DumpHealDBOpenSource_20260828/` (546 MB, 33 files).
  - 0327: `g0327_DumpHealDBOpenSource20250327/DumpHealDBOpenSource20250327/` (404 MB, 21 files); `g0327_DumpHealDBComplete20250327/DumpHealDBComplete20250327/` (1.1 GB, 41 files); `g0327_DumpHealDBOpenSourceDDLs20250327/...` (88 KB, 21 files).
  - 0605 OpenSource: `g0605_DumpHealDBOpenSource20250605/Dump20250605 (1)/` (582 MB, 33 files). Note the space and "(1)" in the path.
  - 0605 Complete: `g0605_DumpHealDBComplete20250605/Dump20250605/` (1.2 GB, 44 files).
  - DDL-only: `v1_ddl_0711`, `v2_ddl_0828`, `g0605_DumpHealDBOpenSourceDDLs20250605`, `code_ddl_complete_0828`, `code_ddl_os_0828`.
  - V1 equals 0605 OpenSource. The inventory md5s match after dropping the `-- Dump completed on` line.
- **File names** are `healdb_<table>.sql`. Bytes and rows per table:

| table | V1 (= 0605) | V2 | 0327 OpenSource |
|---|---|---|---|
| api_response | 157,008,125 (7,447 rows) | 84,813,143 (7,447; adds `ds_text_submitted`) | 70,119,293 (7,447) |
| entity | 74,670,702 (274,010) | absent | absent (old `hd_int_med_disease_map`: 83,102,166; 240,425 rows) |
| trait | 21,899,554 (469,957) | absent | absent |
| medication_disease | 4,477,165 (43,194) | 3,023,364 (27,861; has `vl_icd_score`, `tp_icd_score`) | 1,109,770 (31,738; 6 columns) |
| medication_disease_extend | 4,642,745 (44,233) | absent | absent |
| entity_icd | absent | 104,048,232 (375,595) | absent |
| entity_trait | absent | 4,396,290 (107,543) | absent |
| cutoff_audit | absent | 28,874,625 (75,119) | absent |
| translate_eng_leaflet_section | 17,131,650 (7,473) | identical | 8,045,676 (3 columns) |
| medication_drug_leaflet | 240,837,256 (7,473) | identical | 235,861,086 |
| wrk_med_leaflet_section | 51,710,686 (7,467) | identical | Complete only: 46,734,596 |
| medication | 1,012,383 (10,548) | identical | identical |
| icd_group / category / subcategory | 45,944 (275) / 336,411 (2,045) / 2,436,876 (12,451) | identical | 33,244 / 245,052 / 1,667,363 (smaller, so the hierarchy changed) |

## 3. Columns and samples
- **api_response**
  - V1: `[id_medication, ds_api_response]`.
  - V2: `[id_medication, ds_text_submitted, ds_api_response]`.
  - V1 and V2 share the same 37 key paths. V2's `ds_text_submitted` for id 4 starts `What this medication is indicated for:\n<drug>, in combination with...`.
- **ACM JSON**, id 4 in V1, `Entities` truncated:
  ```
  {"Entities":[{"Id":10,"Text":"prostate cancer","Type":"DX_NAME","Score":0.8775,"Traits":[{"Name":"DIAGNOSIS","Score":0.53}],
   "Category":"MEDICAL_CONDITION","BeginOffset":257,"EndOffset":272,
   "Attributes":[{"Id":9,"Text":"prostate","Type":"SYSTEM_ORGAN_SITE","Score":0.597,"Traits":[],"BeginOffset":257,"EndOffset":265,"RelationshipScore":0.569},...],
   "ICD10CMConcepts":[{"Code":"C61","Score":0.838,"Description":"Malignant neoplasm of prostate"},...]},...],
   "ModelVersion":"3.0.0.20231001",
   "ResponseMetadata":{"RequestId":"...","HTTPHeaders":{"date":"Thu, 29 May 2025 03:20:50 GMT","content-type":...,"content-length":...,"x-amzn-requestid":...},"RetryAttempts":0,"HTTPStatusCode":200}}
  ```
- **Leaflet tables**
  - `hd_translate_eng_leaflet_section`: `id_medication` (PK), `ds_indication` (Portuguese), `ds_indication_eng` (English), `ds_functionality` (Portuguese), `ds_functionality_eng` (English).
  - `hd_medication_drug_leaflet`: `id_medication` (PK), `dt_publication`, `ds_drug_leaflet_file`, `ds_drug_leaflet_full` (longblob), `ds_indication`, `ds_precaution`, `ds_functionality` (all Portuguese).
  - `hd_wrk_med_leaflet_section`: `id_medication` (no PK, no duplicates), `ds_indication`, `ds_precaution`, `ds_functionality`.
- **Where the text lives**
  - Portuguese indication: `ds_indication` in all three tables. The leaflet and translate copies match in 7,447 of 7,447 rows.
  - English translation: only `ds_indication_eng` (and `ds_functionality_eng`) in the translate table.
- **Example**, id 4 (ABBA):
  - translate `ds_indication` (len 1,020): ` Abba, em combinação com os medicamentos prednisona ou prednisolona e terapia de privação androgênica...`
  - translate `ds_indication_eng` (941): `Abba, in combination with the medications prednisone or prednisolone and androgen deprivation therapy (...), is INDICATED for: - the treatment of patients with prostate cancer...`
  - translate `ds_functionality_eng` (385): `Abba selectively inhibits an enzyme necessary for the production of androgens...`
  - drug_leaflet: `dt_publication` `'2021-11-18'` (a str), `ds_drug_leaflet_file` `'bula_1685668977590.pdf'`, `ds_drug_leaflet_full` (20,752 chars) starts `Modelo de bula – Paciente Abba (acetato de abiraterona) 250 mg`, `ds_precaution` (7,193) `Hipertensão, hipopotassemia e retenção hídrica...`
  - wrk_med_leaflet_section has the same three Portuguese fields.

## 4. out/ (`W/out/`)
- **Verification of the ACM text**
  - `acm_text_v1_por_resposta.csv` (710 KB, 7,447 rows) and `acm_text_v1_resumo.json` (20 KB).
- **Extend analysis**
  - `extend_amostra.csv` (38 KB, 295 rows); `extend_funil.csv`, `extend_perfil.json`, `extend_resumo.json`, `extend_v2_particao.csv`.
  - `extend_run1_as_described.patch`, `replay_405a10c_extend_run1.csv`, `replay_compare_extend_run1.log`, `replay_extend_run1.log`: the first extend attempt.
- **Replay artifacts**
  - `replay_405a10c.csv`, `replay_405a10c.log` (2 MB), `replay_405a10c.sh.out`, `replay_up.log`, `replay_compare.log`, `replay_extend.log`.
  - `replay_main_import.txt` (`import main` fails on the typo `main_webcralwer`), `replay_pip_freeze.txt`, `replay_extend_pip_freeze.txt`.
- **Provenance and comparison**
  - `compare0327.json`, `geracao2024.json`, `dump0327.log`, `v2_backspace_check.csv` and `.log`.
- **Schema and code matrix**
  - `inventario_sql.csv` (320 files), `esquema.json`, `dados.csv`, `matriz.csv`, `codigo_2026.csv`, `codigo_colunas.json`, `load.log`.
  - `codigo_insert_vs_ddl.json`, `metadados_vs_ddl.json`, `redu_versions.json` have no producing script in `scripts/`.
- **Git-history evidence**
  - `nlp_timeline.tsv`, `nlp_blobs.tsv`, `nlp_publico.tsv`, `nlp_extend_ausencia.txt`, `doc_evidencias.txt`.
- `prehist_nested.txt` exists (not opened).

Header plus 2 rows:
```
extend_amostra.csv
id_med_disease,id_medication,cd_icd_full,id_icd_group,id_icd_cat,id_icd_subcat,vl_score,vl_entity_score,fl_low_confidence,nm_trait_main,vl_trait_main_score,padrao_hierarquia,em_md,regra_estrita,top1_cutoff_audit_v2,top5_entity_icd_v2,motivo
23302,4,C61,32,226,1045,0.6668867468833923,0.9201511740684508,1,DIAGNOSIS,0.8787732124328613,GCS,S,S,S,S,borda: primeiro id
23309,7,R50.9,,,7041,0.8484809398651123,0.9584784507751464,0,SYMPTOM,0.9817302823066713,--S,S,S,S,S,borda: maior vl_entity_score

acm_text_v1_por_resposta.csv
id_medication,fase,http_date,model_version,len_s,len_candidato,truncado,n_entidades,n_atributos,n_spans,n_spans_ok,spans_copia1,spans_copia2,camada,chars_cobertos,frac_coberta,max_end_offset,cauda
1,1,2025-05-29T03:20:46Z,3.0.0.20231001,211,490,0,10,4,14,14,7,7,ambas,252,0.514286,489,1
4,1,2025-05-29T03:20:50Z,3.0.0.20231001,941,1950,0,10,20,30,30,15,15,ambas,332,0.170256,1780,170

replay_405a10c.csv (columns after the first 8 left out of the rows)
table,rows_healdb,rows_v1,fingerprint_healdb,fingerprint_v1,fingerprint_equal,except_healdb_minus_v1,except_v1_minus_healdb,examples_healdb_minus_v1,examples_v1_minus_healdb,natural_key,key_dup_healdb,key_dup_v1,key_in_both,key_only_healdb,key_only_v1,key_in_both_other_cols_differ,ids_differ_on_key,ids_equal,id_range_healdb,id_order_inversions_healdb,id_range_v1,id_order_inversions_v1
hd_int_med_disease_entity,274010,274010,1578511417...,1578513691...,False,1,1,...
hd_int_med_disease_trait,469957,469957,2711324119...,2711324119...,True,0,0,...
```

## 5. code/ and src/
- **`W/code/405a10c/`** (14 MB, 62 files) is a `git archive` of commit 405a10c: `main.py`, `db_utils.py` (hardcoded DB credentials, not printed) and `src/`.
  - `src/` holds `nlp_extraction/` (extract, process, link, translate), `repositories/`, `translation/`, `interoperability/`, `webcrawler/`. Most of the size is `chromedriver.exe`.
  - `W/code/405a10c_extend/link_extend_reconstructed.py` (6 KB) is the patched link script.
- **`W/src/`**
  - `git0327` (110 MB): three `.7z` from commit 0e43ed9.
  - `git0605` (139 MB): three `.rar` from 405a10c.
  - `git_meta` (596 KB): metadata xlsx and model png from 405a10c and 4895898.
  - `redu` (183 MB): REDU Dataverse downloads. V1 and V2 dump zips (96 MB and 94 MB), structure zips, metadata xlsx, model png and svg.
  - `prehist_git` (9.0 MB): exists (not opened).

## 6. Grouping feasibility (about 15 s to run)
- V1 has 7,447 medications with an ACM response, and every one has a translate row.
- **English** (`ds_indication_eng.strip()`):
  - 7,044 distinct texts. The count is 7,049 without strip and 6,998 after lowercasing and collapsing whitespace.
  - The largest group has 39 medications: "This MEDICINE is INDICATED as an analgesic (for pain) and antipyretic (for fever)."
  - 197 groups have more than one medication, covering 600 medications. 6,847 are singletons.
  - Grouping saves only 403 of 7,447 calls (5.4%).
- **Portuguese** (`ds_indication.strip()`):
  - 6,250 distinct texts (6,505 raw). The largest group has 49.
  - 469 groups have more than one medication, covering 1,666. 5,781 are singletons.
  - There are 7,136 distinct (English, Portuguese) pairs, against 6,250 Portuguese and 7,044 English. Identical Portuguese texts therefore received different English translations.
- **Shared leaflet id: none.**
  - `hd_medication_drug_leaflet` has a 1:1 PK on `id_medication`. `ds_drug_leaflet_file` is unique across all 7,473 rows.
  - `hd_wrk_drug_leaflet` (8,469 rows) and `hd_wrk_drug_leaflet_dedup` (7,634 rows) are also unique per file.
  - For context, `hd_medication` has 10,548 rows, 7,651 distinct names and 2,494 distinct `ds_active_ingredients`.
- **English text length in characters** (after strip):

| set | min | median | p90 | p99 | max |
|---|---|---|---|---|---|
| ACM set (7,447) | 30 | 337 | 1,003 | 2,565 | 9,177 |
| Portuguese, ACM set | 26 | 358 | 1,123 | n/a | 27,627 |
| V1 candidate before the 10k cut | 128 | 742 | 2,075 | n/a | 18,422 |
