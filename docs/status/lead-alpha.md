# Status — Lead α

## Estado

α1 concluído; α2 em andamento (núcleo do pipeline).

## Feito

- `41fe19c` data: leitor de mysqldump em streaming (`data/dumps.py`) e snapshots Parquet com `manifest.json`
  (`data/store.py`) em `/home/vinicius/hab-data/snapshots/{v1,v2,g0327}`.
- `cb51181` pipeline: três níveis de igualdade (`pipeline/equality.py`); tabelas V1 `entity` e `trait` rederivadas das
  respostas (`pipeline/tables_v1.py`), iguais ao dump em todas as colunas e na ordem.

## Em andamento

- α2: `pipeline/{catalog,evidence,core,mapping,semantics,trace}.py` (escrito pelo lead), md/extend V1, V2.

## Próximo

- GATE 1; α3 (grupos, estratos, splits); α4 (Estudo A).

## Testes

- `uv run pytest tests/test_data_dumps.py tests/test_data_store.py -q` → `40 passed in 2.61s` (inclui os 19 `dumps`).
- `uv run pytest -m dumps tests/test_pipeline_tables_v1.py -q -s` → `1 passed, 7 deselected in 23.11s`
  (rebuild 13.9 s, compare 7.4 s; entity 274.010 e trait 469.957 linhas, 0 diferenças, ordem igual).

## Números re-derivados

| valor | comando | arquivo |
|---|---|---|
| V1 entity 274.010 linhas = dump (todas as colunas, ordem PK) | `uv run pytest -m dumps tests/test_pipeline_tables_v1.py` | `src/habench/pipeline/tables_v1.py` |
| V1 trait 469.957 linhas = dump | idem | idem |
| Contagens de linhas dos snapshots (matriz F2) | `uv run pytest -m dumps tests/test_data_store.py` | `src/habench/data/store.py` |

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
