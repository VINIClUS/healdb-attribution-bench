# Status — Lead β

## Estado

β1 concluído; β2 (SPEC) em andamento.

## Feito

- Leitura: CLAUDE.md, 00_common, lead-beta, protocolo v0.2, `docs/design/*.md`, `docs/decisoes.md`, `docs/deviations.md`,
  F1, F2, F3 (pdftotext).
- Identidade das fontes conferida (ver Números re-derivados).
- β1: `docs/analise/00_analise_protocolo.md` (38 citações, 21 checagens internas, resoluções R01–R30, achados E01–E17).

## Em andamento

- β2: `docs/SPEC.md`.

## Próximo

- `tests/data/spec_examples.json`, `tests/test_spec_examples.py` → GATE 2.

## Testes

- `uv run pytest -q` → `3 passed` (antes do β2).

## Números re-derivados

| valor | comando | arquivo |
|---|---|---|
| SHA-256 `bd466b36…d1f4`, 33.897 bytes | `sha256sum`; `os.path.getsize` via `uv run python` | `/home/vinicius/code/HealDB/doc/PROVENIENCIA_NLP_V1.md` (F1) |
| SHA-256 `856d5c31…d515`, 21.480 bytes | idem | `/home/vinicius/code/HealDB/doc/RECONSTRUCAO_V1_MATRIZ.md` (F2) |
| SHA-256 `822750b7…a4ff` | `uv run python -c "import hashlib;..."` | `/home/vinicius/Downloads/Esboco_revisado_HealDB_IC_Unicamp(2).pdf` (F3) |
| SHA-256 `7bfed6c0…a34c` | `sha256sum` | `docs/protocolo/Protocolo_Experimental_HealDB_Revisado_v0_2.md` |

Todos iguais a `docs/protocolo/SHA256SUMS` e, para F1/F2, aos hashes e tamanhos citados no próprio protocolo.

## Perguntas / BLOCKED

(nenhuma)

## Desvios propostos

- **P-β1 (níveis queimados).** `docs/design/desenho_inicial.md` §C nomeia candidatos a níveis de teste. Proposta:
  tratar todo valor citado em `docs/design/` ou em `docs/SPEC.md` como queimado e excluí-lo da lista selada de níveis
  de teste (R28). O SPEC não repete esses valores.
- **P-β2 (H2 não confirmatória nesta fase).** A campanha de teste não está autorizada (`decisoes.md`), então o terceiro
  contraste primário de §11.3 entra no Holm com p = 1 e o piloto dev/cal é exploratório (R15, R18).
- **P-β3 (citações).** Corrigir as seções citadas em §1.1 (C08, C09) e a fonte de §4.1 (C23) na versão confirmatória.

## REQUEST

(nenhum)
