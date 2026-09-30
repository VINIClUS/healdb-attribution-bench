GATE1: passed

```
uv run pytest -m dumps tests/test_pipeline_fidelity.py tests/test_pipeline_tables_v1.py tests/test_pipeline_tables_v2.py tests/test_pipeline_semantics.py tests/test_data_dumps.py tests/test_data_store.py -q -rA
PASSED tests/test_pipeline_fidelity.py::test_md_equal_dump_all_columns_and_ids
PASSED tests/test_pipeline_fidelity.py::test_v1_funnel
PASSED tests/test_pipeline_fidelity.py::test_extend_equal_dump_inferred_rule
PASSED tests/test_pipeline_fidelity.py::test_cm_space_presence_equals_md
PASSED tests/test_pipeline_fidelity.py::test_hierarchy_version_equal_v1_v2
PASSED tests/test_pipeline_fidelity.py::test_full_v1_run_under_60s          (parse+hierarchy 3.0s, run 4.8s)
PASSED tests/test_pipeline_fidelity.py::test_64_hybrids_v1_to_v2_under_120s (64 hybrids 25.0s)
PASSED tests/test_pipeline_tables_v1.py::test_v1_tables_equal_dump          (rebuild 13.3s, compare 7.1s)
PASSED tests/test_pipeline_tables_v2.py::test_v2_entity_icd_and_trait_equal_dump
PASSED tests/test_pipeline_tables_v2.py::test_v2_audit_and_md_equal_dump
PASSED tests/test_pipeline_tables_v2.py::test_core_v2_preset_agrees_with_md
PASSED tests/test_pipeline_semantics.py::test_dummy_sound_on_v1_sample
(+ 19 row-count tests of tests/test_data_{dumps,store}.py)
31 passed, 53 deselected in 103.79s (0:01:43)
```

# Status — Lead α

## Estado

GATE 1 aprovado; α3 em revisão.

## Feito

- `41fe19c` data: leitor de mysqldump em streaming (`data/dumps.py`) e snapshots Parquet com `manifest.json`
  (`data/store.py`) em `/home/vinicius/hab-data/snapshots/{v1,v2,g0327}`.
- `cb51181` pipeline: três níveis de igualdade (`pipeline/equality.py`); tabelas V1 `entity` e `trait` rederivadas das
  respostas (`pipeline/tables_v1.py`).
- Núcleo (`pipeline/{catalog,evidence,core,trace,mapping,semantics}.py`, escrito pelo lead): uma função parametrizada e
  determinística sobre o JSON (ordem dos arrays preservada), presets `V1`/`V2`, catálogo de fatores (pré-ACM como
  indisponíveis), trace por etapa, certificados de fator mudo (`semantics.dummy`, só prova irrelevância).
- Fidelidade exata (todas as colunas, ordem e ids):
  - V1: `entity` 274.010, `trait` 469.957, `md` 43.194 (ids 1..43.194), funil 274.010 → 265.587 → 259.198 → 171.713 →
    43.194 → 43.194; `extend` 44.233 (ids 23.302..67.534; **regra inferida**, F1 §2.4).
  - V2 (secundário, também exato): `entity_icd` 375.595, `entity_trait` 107.543, `cutoff_audit` 75.119, `md` 27.861
    (atributos inclusive; 0 empates no GROUP_CONCAT). O preset `V2` do núcleo concorda com o `md` V2 em presença e score.
- Diferença de 1 ULP (med 560, C49.9): não aparece; Python lê o texto decimal do dump e o JSON com o mesmo valor.

## Em andamento

- α3: grupos, estratos, splits (worker terminou; revisão do lead).

## Próximo

- α4: manifesto de fontes, scripts de replay Docker (READY_FOR_DOCKER), `historical/`, claims, relatório do Estudo A.

## Testes

- Não-dumps: `uv run pytest -m "not dumps" tests/ -q` → `154 passed, 31 deselected in 1.08s`.
- Dumps: ver bloco GATE1 acima.

## Números re-derivados

| valor | comando | arquivo |
|---|---|---|
| V1 entity 274.010 / trait 469.957 = dump | `uv run pytest -m dumps tests/test_pipeline_tables_v1.py` | `pipeline/tables_v1.py` |
| V1 md 43.194 = dump, funil exato | `uv run pytest -m dumps tests/test_pipeline_fidelity.py` | `pipeline/core.py`, `tables_v1.py` |
| V1 extend 44.233 = dump (regra inferida) | idem | idem |
| V2 entity_icd/entity_trait/cutoff_audit/md = dump | `uv run pytest -m dumps tests/test_pipeline_tables_v2.py` | `pipeline/tables_v2.py` |
| Contraste V1→V2 nas respostas V1 (espaço OMS): md V1 projetado 34.101 chaves; 27.405 aparecem, 18.284 somem | `test_64_hybrids_v1_to_v2_under_120s` | `pipeline/core.py` |
| Formas das famílias (corpus inteiro, descritivo, D2): 27.874 / 14.182 / 3.464 / 168 / 1 (1–5 conjuntos); 4.555 não monótonas; participação sel 23.425, occ 18.859, trait 17.561, icd_thr 12.784, ent_thr 2.287, map 0 | script ad hoc (a portar para `historical/`) | — |
| Versão da hierarquia igual V1/V2: `hier:61ad55c843029102` | `test_hierarchy_version_equal_v1_v2` | `pipeline/mapping.py` |
| Respostas: V1 7.447 (0 NULL, 258 vazias, 113 com Id repetido); V2 7.447 (0 NULL, 277 vazias, 71 Id repetido); 0327 7.447 (0 NULL, 288 vazias, 34 Id repetido) | sonda ad hoc | — |

## Decisões de semântica híbrida (não cobertas pelo desenho; fixadas em `catalog.py`)

- `occ=per_entity_any` com `sel=all`: um registro por (Id da entidade, código), como as linhas de `entity_icd`.
- `sel=top1` sob `occ=last_upsert`: top-1 por Id emitidos na ordem da primeira ocorrência do Id; depois agrupados por
  código, a última ocorrência define os escores.
- `occ=first_upsert`: a primeira ocorrência define escalares e escores de traits.
- `map=who_exact`: subcategoria exata ou categoria exata de 3 caracteres, sem fallback de prefixo.
- Níveis extras de `trait`: `v1_hyp_le_0.6` (cabeçalho do código), `v1_no_required`, `neg_only`.
- `cm_ungated` no espaço OMS: códigos sem projeção ficam em `RunResult.unmapped`, não viram ausência; em níveis `who_*`,
  NO_MAP é o filtro histórico da V2 (descarte).
- Limiares aceitam qualquer float em [0, 1]; os níveis listados são a grade catalogada.

## Perguntas / BLOCKED

(nenhuma)

## Desvios propostos

- **`flock` bloqueado.** A camada de permissões rejeita `flock ... uv run pytest` ("runs its argument as a command").
  Os testes `dumps` rodam como `uv run pytest -m dumps <arquivo>`, sem o lock. O primeiro build dos snapshots rodou
  sem o lock, porque o `addopts` do `pyproject.toml` não exclui `dumps` e um worker rodou `uv run pytest` puro.
  Proposta: liberar `flock` nas permissões ou excluir `dumps` do `addopts`.
- **Nível 1 de igualdade "como despejado".** `ds_api_response` é uma coluna JSON do MySQL: o dump traz a
  re-serialização do MySQL, não os bytes enviados pelo ACM. Afirmações de nível 1 valem para o texto do dump.

## REQUEST

- `.gitignore`: o padrão `data/` ignora também `src/habench/data/`. Ancorar como `/data/` (e idem `truth/`, `views/`,
  `runs/`). Até lá, os arquivos de `src/habench/data/` entram com `git add -f`.
