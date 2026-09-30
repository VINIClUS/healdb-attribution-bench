# Mapa do código NLP do HealDB (V1 @405a10c e V2 @HEAD)

> Relatório de subagente (Sonnet) produzido em 2026-09-30 na sessão de planejamento, somente leitura.
> Números aqui são de rascunho: re-derivar em código versionado antes de citar em relatório.
> Onde se lê ThesisBench/thesisbench, leia healdb-attribution-bench/habench.

Nothing in the repo was modified. Credentials are present in `db_utils.py` (tracked, password line unchanged since 405a10c). `config.py` is gitignored, is imported for `AWS_CONFIG`, `OPENAI_API` and `PATHS`, and was not opened.[trecho removido: referência a material com credenciais]

## 0. Scope and versions
- **Versions:**
  - V0 is `0e43ed9` (2025-03-27). `link` reads `ht_int_med_disease_map`, keeps score > 0.7, and adds the top 3 if ≤ 5 pass.
  - V1 is `405a10c` (2025-06-06). `c5b0db1` only wires `main` and renames variables in `link`.
  - V2 is `4895898` (2026-01-06). `2d1dc7f` only adds progress prints.
  - HEAD `8ea0479` equals the working tree for every file below.
- **Files:** all in `/home/vinicius/code/HealDB/src/nlp_extraction/`.
- **Your docs:** `doc/PROVENIENCIA_NLP_V1.md` (PROV) and `doc/RECONSTRUCAO_V1_MATRIZ.md` (both untracked) agree with what follows. I cite them instead of repeating counts.
- **Orchestration:** `main_nlp_extraction.py` @405a10c runs only `link` (lines 10–13 and 42–45 are commented out). `c5b0db1` and HEAD run all five steps with no arguments, so the V2 defaults apply.

## 1. V1 @405a10c

**`extract_diseases_from_indications.py` (102 lines)**
- 36–43 read `id_medication, ds_indication_eng, ds_functionality_eng` from `hd_translate_eng_leaflet_section` where `length(ds_indication_eng) > 10 AND id_medication in (3205, 4139)`. The ID filter is a test filter (PROV §4.5).
- 52: `ds_functionality_eng = row[1]`. This sends the indication twice.
- 54–59 build `"What this medication is indicated for:\n" + ind.strip() + "\n\n" + "How this medication works:\n" + func.strip()`.
- 61: `full_text = full_text[:10000]`. The cut is in characters.
- 67: `infer_icd10_cm(Text=full_text)`, with no other parameter.
- 82–89 upsert `hd_int_med_disease_api_response(id_medication, ds_api_response)`. The submitted text is not stored. Errors print and `continue`.

**`process_disease_data_json.py` (126 lines)**
- 30–31 run `TRUNCATE ..._trait` and `DELETE FROM ..._entity`. 35–38 read all `api_response` rows.
- Entity fields (56–63): Text→`ds_icd_aggreg`, Type→`tp_entity`, Score→`vl_entity_score`, Category→`tp_category`, offsets, Attributes.
- Concept fields (65–68): Code→`cd_icd_full`, Score→`vl_score`, Description→`ds_icd`. Both scores are copied from ACM, never computed.
- 78–95 upsert `hd_int_med_disease_entity` with every non-key column `=VALUES(...)`. That implies key (id_medication, cd_icd_full), so the last occurrence wins.
- 105–117 sit inside the concept loop and upsert `hd_int_med_disease_trait` on (id_medication, cd_icd_full, nm_trait).
- Net effect:
  - Scores come from the last occurrence of (med, code).
  - Traits are the union over all occurrences, including both copies of the duplicated text, with the last score per trait name.
  - Traits are copied to every concept of the entity.
  - An entity with no concepts stores nothing.
- The keys are inferred. The V1 DDL exists only in the unreadable 0605 `.rar`. The inference is consistent with PROV §2.2 and your replay.

**`link_medications_with_diseases.py` (178 lines)**
- 72–80 select entity `LEFT JOIN` trait on (id_medication, cd_icd_full), with `REPLACE(e.cd_icd_full,'.','')` as the no-dot code. There is no ORDER BY.
- Hierarchy gate, 111–130:
  - Pass if the category equals the no-dot code, or the subcategory equals it.
  - Otherwise pass if `nodot[:3]` is a category, else `continue`.
  - Net: the 3-character prefix must be in `hd_icd_category`.
- Filters, condensed but with the original line numbers:
```
135 if trait_names & {"LOW_CONFIDENCE","NEGATION","PERTAINS_TO_FAMILY"}: continue
137 if any(t[0]=="HYPOTHETICAL" and (t[1] or 0) > 0.65 for t in traits): continue
141 if vl_score >= 0.6 and vl_entity_score >= 0.6:
143-144 valid_trait = any(t[0] in {"DIAGNOSIS","SYMPTOM","SIGN"} or (t[0]=="HYPOTHETICAL" and (t[1] or 0) <= 0.6) ...)
155 sorted_traits = sorted(traits, key=lambda x: x[1] or 0, reverse=True)
158 fl_low_confidence = vl_score < 0.7 or vl_entity_score < 0.7
```
- 40–67 (`search_repository_icd`, called at 160): the category from `nodot[:3]` gives group and category. An exact subcategory joined to its category then overrides all three IDs.
- 162–174 insert `hd_medication_disease(id_medication, cd_icd_full, id_icd_group, id_icd_cat, id_icd_subcat, vl_score, vl_entity_score, nm_trait_main, vl_trait_main_score, fl_low_confidence)`.
  - `cd_icd_full` is the dotted ICD-10-CM code from ACM.
  - There is no truncate, no upsert, and a commit per row.
  - The outer `try` (177) ends the whole loop at the first error.
  - The V1 layout matches the `hd_medication_disease_extend` DDL in `doc/DDLsHealDBOpenSource20260106.zip@429b05a`, which has no unique key. An operator must clear the table first.
- **Doc and code drift:**
  - The header (line 24) says HYPOTHETICAL is accepted at ≤ 0.6, but the code rejects at > 0.65. That leaves a dead zone of (0.6, 0.65].
  - `valid_trait` also drops entities with no traits. It removed 0 rows on V1 data (PROV §2.3).
  - `nm_trait_main` ties fall to SQL row order, which is PK order and therefore alphabetical (PROV §2.2).

## 2. V2 @HEAD

**`extract_diseases_from_indications.py` (127 lines)**
- SQL 37–63 reads `hd_translate_eng_leaflet_section t JOIN hd_medication m` where `LENGTH(t.ds_indication_eng) > 10`. It nests two replacements:
  - `REGEXP_REPLACE(..., CONCAT('\\b', <escaped nm_medication>, '\\b'), '<drug>', 1, 0, 'i')`
  - `REGEXP_REPLACE(..., 'with[[:space:]]+or[[:space:]]+without', 'regardless of', 1, 0, 'i')`
- **Bug:** lines 45 and 51 write `'\\b'` in a non-raw Python string. MySQL receives `'\b'`, which is a backspace. The `<drug>` substitution therefore never matches, while "with or without" does. PROV §4.6 confirms this empirically and shows the main run used a different, uncommitted SQL.
- 75 uses `row[2]`. 76–82 build `header + ind.strip() + "\n\n"`; the functionality section is commented out at 79–81. 84 cuts at `[:10000]`.
- 105–113 upsert `api_response(id_medication, ds_text_submitted, ds_api_response)`, updating both columns on duplicate.

**`process_disease_data_json.py` (164 lines; signature `truncate_before_load=True, batch_size=2000`)**
- 39–40 truncate `entity_icd` and `entity_trait`. 44–48 read rows where `ds_api_response IS NOT NULL`.
- 98–102: `nr_entity_id = entity["Id"]`, with the loop index as fallback.
- 116–121: one trait row per (entity, trait), independent of concepts.
- 124–135: one row per (entity, concept) for every concept returned. The cap of 5 comes from ACM, not from code. Committed samples in `data/output/interoperability/*response*.json` @405a10c show a maximum of 5 concepts, sorted by score descending, on every entity. They show only DX_NAME / MEDICAL_CONDITION entities, `Id` on every entity, and ModelVersion `3.0.0.20231001`.
- Upserts (53–81) use PKs (id_medication, nr_entity_id, cd_icd_full) and (id_medication, nr_entity_id, nm_trait), confirmed in the DDL.

**`link_medications_with_diseases.py` (352 lines)**
- **Signature and defaults (37–45):** `entity_score_min=0.70, icd_medium_min=0.30, icd_high_min=0.60, truncate_audit=True, truncate_final=True`. 48–50 set them as session variables.
- **Audit (68–241),** one row per entity, PK (id_medication, nr_entity_id):
  - Top-1 concept is `ROW_NUMBER() OVER (PARTITION BY id_medication, nr_entity_id ORDER BY vl_icd_score DESC, cd_icd_full)`, then `rn = 1` (85–107).
  - `fl_negation` is `MAX(CASE WHEN nm_trait='NEGATION'...)` (114). It ignores the trait score, and every other trait is ignored.
  - `nm_trait_main` and `vl_trait_main_score` are for audit only (119–130).
  - Level is HIGH ≥ 0.60, MEDIUM ≥ 0.30, else LOW (204–208).
  - Flags: `fl_pass_dx_name = (tp_entity='DX_NAME')`, `fl_pass_negation`, `fl_pass_entity_score = (vl_entity_score >= @entity_score_min)`, and `fl_pass_all_pre` (225–232).
- **Mapping (134–184, 166–170):**
  - `SUBCAT_EXACT` when `hd_icd_subcategory.cd_subcat` equals the no-dot code.
  - `CAT3_FALLBACK` when `hd_icd_category.cd_cat` equals `LEFT(nodot,3)`.
  - `NO_MAP` otherwise.
  - IDs come from `COALESCE` (173–175).
- **Final (250–343):**
  - Eligible rows have `fl_pass_all_pre = 1 AND cd_icd10_nodot IS NOT NULL` (279–280).
  - `GROUP BY id_medication, cd_icd10_final` takes `MAX(vl_icd10cm_score)`. The best row is picked by `GROUP_CONCAT ... ORDER BY vl_icd10cm_score DESC, vl_entity_score DESC` (284–313).
  - `tp_icd_score` is recomputed (316–325), then 342 filters `IN ('MEDIUM','HIGH')`. The effective cut is ICD score ≥ 0.30.
  - The stored `cd_icd_full` is the mapped dotless WHO ICD-10 code.
- **Misalignment (297–305):** `GROUP_CONCAT` skips a NULL `nm_trait_main`, but `COALESCE(vl_trait_main_score,0)` does not. If the best row has no traits, the name and score can come from different rows.

## 3. Translation
- **Location:** the leaflet translation is `src/nlp_extraction/translate_leaflet_sections.py` (191 lines), not `src/translation/`.
  - It is identical at 405a10c and HEAD.
  - It was renamed from the indication-only `translate_leaflet_indication.py` (0e43ed9), which used `time.sleep(15)` and a Portuguese prompt.
  - `src/translation/*` differs from 405a10c only by the removed gitlink `healdb`.
- **Service:** OpenAI chat completions via `requests.post(..., timeout=60)` (84). URL, headers and model come from `config.OPENAI_API`. The docs say GPT-3.5 (readme l.539, PDF v14 p.13). No tracked file states the exact model ID.
- **Prompt (81):** a single user message, `f"Translate to English and return only the translation: {ds_field}"`.
- **Parameters:**
  - No temperature, max_tokens or seed appears anywhere in `src/` (grep), so service defaults apply and output is stochastic.
  - Input is cut to 6000 characters (74–75).
  - Failures silently return `""` (86–99).
- **Tables:**
  - Reads `hd_medication_drug_leaflet` (`ds_indication`, `ds_functionality`).
  - Inserts into `hd_translate_eng_leaflet_section` only if it is empty (165–175).
  - Selects rows missing either English column (107–115) and updates both per row (48–53).
  - Sets `ds_indication_eng=''` where `length(ds_indication) <= 10` (26–30).
- **Flag (inference):** a row missing only one English column gets both re-translated and overwritten. PROV §4.7 finds indications stable from 0327 to 0605, so the committed path probably is not what ran on 2025-05-29.
- **Other `src/translation` modules:**
  - They also call OpenAI through `requests`.
  - Active ingredients PT→EN use the prompt "traduzir para o inglês e retornar apenas a tradução" (gpt-4-0314 per the PDF).
  - Drug and food interactions go EN→PT (GPT-3.5, private tables).
  - ICD descriptions use the WHO 2008 CSVs first, with GPT as fallback.
  - None of them feeds ACM.
- **Section extraction:** `extract_leaflet_sections.py` (328 lines, unchanged since 405a10c) uses regex boundaries to fill `hd_wrk_med_leaflet_section` and `hd_medication_drug_leaflet`.

## 4. ICD hierarchy
DDLs are in `doc/DDLsHealDBOpenSource_20260828.zip`.
- **`hd_icd_group`:** `id_group` PK, `ds_group`, `ds_group_abbrev`, `cd_cat_ini` and `cd_cat_end` (varchar(3)), `ds_group_eng`.
- **`hd_icd_category`:** `id_cat` PK, `id_group` FK, `cd_cat` varchar(3) UNIQUE, `ds_cat`, `ds_cat_abbrev`, `tp_classif`, `cd_refer`, `cd_excluded`, `ds_cat_eng`.
- **`hd_icd_subcategory`:** PK (`id_subcat`, `id_cat`), `cd_subcat` varchar(4) UNIQUE, `ds_subcat`, `ds_subcat_abbrev`, `tp_classif`, `fl_restrgender`, `cd_refer`, `cd_excluded`, `ds_subcat_eng`.
- **Loader:** `src/repositories/create_diseases_repository.py` reads CSVs with dotless codes and sets `id_cat` from `cd_subcat[:3]`.
- **Consequences:**
  - Only 3- and 4-character dotless codes can match exactly.
  - 5–7 character ICD-10-CM codes always fall to the 3-character prefix.
  - Neither version tries a 4-character prefix, so E11.65 goes to E11, not E116.
  - ICD-10-CM-only categories (D49, N52, G89, Z3A) drop out.
- **V1 vs V2:** the ID assignment (V1 40–67 vs V2 141–184) and the gate are equivalent for the same code. The real differences are:
  - the stored code (dotted ICD-10-CM vs dotless WHO ICD-10);
  - the dedup key;
  - V2 takes the top-1 concept before mapping, so a NO_MAP top-1 drops the entity even if concept 2 would map;
  - V2 labels an exact 3-character category hit `CAT3_FALLBACK`;
  - V2 can hold both E11 and E119 for one medication.

## 5. Environment
- **`main.py`:**
  - It runs Webcrawler, Repositories, Translation, NLP, Interoperability and RDF in sequence.
  - It is identical at 405a10c and HEAD.
  - Line 10 imports `src.webcrawler.main_webcralwer` (typo; the file is `main_webcrawler.py`), which raises `ModuleNotFoundError`.
  - Run the NLP step alone with `python src/nlp_extraction/main_nlp_extraction.py`.
- **`db_utils.py`:**
  - `open_connection()` uses mysql.connector, and `open_connection_alchemy()` uses `mysql+pymysql`.
  - The database is `healdb`.
  - The host is 127.0.0.1:3306 @405a10c and a placeholder at HEAD (`dbb0b9b`).
- **`requirements.txt`:**
  - 19 lines, unpinned, identical at 405a10c and HEAD. It lists boto3, mysql-connector-python, pymysql, requests, pandas, numpy, selenium, bs4, rdflib, SPARQLWrapper, matplotlib, seaborn and squarify.
  - It is missing `sqlalchemy`, which `db_utils.py:4` imports at module level, so every entry point needs it. Also missing: pytesseract, PyMuPDF, Pillow, lxml and chardet.

## 6. Data flow
- **V1:**
  1. `Entities[]` and `ICD10CMConcepts[]` become entity rows (upsert on med + code).
  2. `Traits[]` become trait rows (upsert).
  3. `link` applies gate, trait veto, score ≥ 0.6 on both scores, then `valid_trait`.
  4. Survivors go into `hd_medication_disease`.
- **V2:**
  1. `Entities[].Id` gives `entity_icd` (entity × every concept) and `entity_trait`.
  2. `cutoff_audit` holds the top-1 concept, the NEGATION flag, the mapping and the pre-filter flags, one row per entity.
  3. `hd_medication_disease` takes eligible rows, groups by mapped code, keeps the max ICD score, and keeps only MEDIUM/HIGH.

## 7. Candidate factors
Post-ACM factors can be replayed offline from the `api_response` JSON, keeping array order. The V1 `entity` and `trait` tables are lossy, so V2-style factors cannot be computed from them. Pre-ACM factors need a matching new ACM response, so a counterfactual is unavailable without one (protocol §7.3).

| Factor | V1 | V2 / alternative |
|---|---|---|
| Occurrence rule (post) | Last occurrence sets the scores; traits are the union over all occurrences, so any negated mention vetoes the pair | Decision per `nr_entity_id`, then MAX over entities |
| Concept selection (post) | Every returned concept independently | Top-1 per entity, ties by code ascending |
| Select vs map order (post) | Map each concept, then filter | Select top-1, then map |
| ICD score threshold (post) | ≥ 0.6 | ≥ 0.30 (MEDIUM), HIGH ≥ 0.60 is a label; V0 was > 0.7 plus top-3 |
| Entity score threshold (post) | ≥ 0.6 | ≥ 0.70 |
| Entity type filter (post) | None | `DX_NAME` (likely a no-op, all entities are DX_NAME) |
| Trait veto set (post) | {LOW_CONFIDENCE, NEGATION, PERTAINS_TO_FAMILY} | {NEGATION} only |
| HYPOTHETICAL rule (post) | Reject > 0.65; docs say ≤ 0.6 | None |
| Required trait (post) | DIAGNOSIS, SYMPTOM, SIGN, or HYPOTHETICAL ≤ 0.6 (0 effect on V1 data) | None |
| Mapping policy and code system (post) | Keep dotted ICD-10-CM if the 3-character prefix exists | Project to WHO ICD-10: exact 4-character, else 3-character, else drop |
| Dedup key (post) | (med, dotted ICD-10-CM) | (med, mapped code) |
| Confidence output (post) | `fl_low_confidence` (< 0.7 on either score) | 3-level `tp_icd_score` |
| Tie-breaking (post) | Row and PK order | Explicit, except undefined `GROUP_CONCAT` ties |
| Header and second section (pre) | Header + s + `\n\n` + H + s, indication duplicated | Header + s + `\n\n` |
| `<drug>` substitution (pre) | None | Intended on, committed SQL is a no-op |
| "with or without" (pre) | None | Replaced by "regardless of" |
| Character cuts (pre) | 10,000 | 10,000; translation input 6000 |

- **Likely no-ops:** the hierarchy ID logic and `valid_trait` on V1 data.
- **Pairs to define jointly:**
  - concept selection with select-vs-map order;
  - mapping policy with dedup key;
  - occurrence rule with trait veto set;
  - score thresholds with the confidence output.
- **Confound for V1 versus V2:** ACM model version, `3.0.0.20231001` for V1 and `3.2.0.20251001` for V2 (PROV §4.5–4.6). V2 `ds_text_submitted` is ground truth for its input, while the V1 text is only reconstructed (PROV §4.2).
