DONE: α

# Status — Lead α

## Estado

α1–α4 concluídos. GATE 1 aprovado e reconferido depois da última mudança em `pipeline/core.py`, que só alterou uma
docstring. O replay Docker foi executado pela sessão principal e está registrado. O REQUEST do lead β (regras dummy,
SPEC 4.6) está atendido.

## Feito

- **α1–α2 (GATE 1).**
  - Snapshots Parquet e leitor de dumps.
  - Núcleo parametrizado (`pipeline/`) com fidelidade exata V1 e V2 (tabelas abaixo).
- **α3.** 5.087 grupos documentais, 13 estratos, semente 20260930 e selagem (`SealedError`).
- **α4.**
  - `repro/sources_manifest.json`.
  - Texto V1, fases e metadados por chamada: `docs/estudo_a/texto_v1.json`.
  - Identidade V1 = 0605: `docs/estudo_a/dumps_v1_0605.json`.
  - Repetibilidade, tradução e contraste: `docs/estudo_a/resultados_estudo_a.json`.
  - `repro/claims_study_a.yaml`, com 24 afirmações.
  - Relatório final: `docs/estudo_a/relatorio_estudo_a.md`.
- **Replay SQL e validação cruzada** (commits `783db26`, `2e8eab4`, `abb34df`, `71eccef`).
  - `repro/replay_manifest.json` registra:
    - a ação de operador "load `hd_medication`";
    - a primeira execução falha;
    - o resultado de `replay.compare`;
    - o resultado da validação cruzada (xval).
  - Claim P1c passa a `rederivado_verificado`; nova claim A-d-xval; relatório §7.
- **REQUEST β, regras dummy** (commits `d833f8c`, `82d585f`).
  - Regra 2 (`sel`) ganhou a condição de ordem por código (EX-30).
  - A regra 3 (`occ`) tinha um contraexemplo, achado pelo teste de propriedade e explicado abaixo; está corrigida.
  - Testes hypothesis de solidez contra força bruta, com `Id` duplicado e empates:
    - `test_dummy_sound_property`: contrastes aleatórios, |D| de 0 a 6, espaços CM e OMS;
    - `test_dummy_sound_property_sel_under_upsert`: dirigido ao formato de EX-29;
    - `test_ex30_sel_order_condition`.
  - Checagem de mutação: sem a condição de ordem, os dois testes dirigidos falham; o teste geral não pega esse caso.
  - Docstring de `core._select` corrigida (sem mudança de comportamento).

## Achado de ambiente (replay)

- **A primeira execução Docker falhou em silêncio.**
  - `up.sh` não carregava `hd_medication`. As 744.590 inserções em `entity` falharam na FK `FK_MEDICATION_ACM2`, e o
    código histórico só imprime o erro.
  - O driver terminou com rc=0 e exportou 0 linhas; a validação cruzada rodou sobre tabelas vazias.
- **Correção (`1c505b0`, sessão principal).** `up.sh` carrega `hd_medication`, e `driver.py` falha quando nenhuma linha
  de `entity` é gravada.
- **Registro.** Está em `failed_runs` e `setup_operator_actions` do manifesto e no relatório §7.1.

## Números re-derivados

| valor | comando |
|---|---|
| V1 `entity` 274.010 e `trait` 469.957 iguais ao dump | `uv run pytest -m dumps tests/test_pipeline_tables_v1.py` |
| V1 md 43.194 igual ao dump, funil exato; `extend` 44.233 (regra inferida) | `uv run pytest -m dumps tests/test_pipeline_fidelity.py` |
| V2 `entity_icd`, `entity_trait`, `cutoff_audit` e md iguais ao dump | `uv run pytest -m dumps tests/test_pipeline_tables_v2.py` |
| Replay `405a10c`: `entity`, `trait` e md iguais aos snapshots (ordem e ids); 1 valor a 1 ULP em (560, `C49.9`); 0 linhas `Error`; 618,4 s | `uv run python scripts/replay/write_manifest.py` |
| Primeira execução: 744.590 erros `FK_MEDICATION_ACM2`, 0 linhas | idem (`failed_runs`) |
| xval: 100 configurações, 1.082 medicamentos de dev, 1.863.659 linhas | `uv run python -m habench.historical.xval compare` |
| xval, chave natural: 100/100 concordam | idem |
| xval, comparação estrita: 0/100 iguais (96.172 linhas diferem só em empates de `nm_trait_main`) | idem |
| Contraste V1→V2, dev+cal e corpus inteiro | `uv run python -m habench.historical.study_a` |
| Entidades com nome de traço repetido: V1 0 de 150.506; V2 0 de 75.913 | sonda ad hoc sobre `load_evidence` (não versionada) |

## Testes

- Suite padrão: `uv run pytest -q` → `606 passed, 46 deselected, 3 warnings in 26.50s`.
- GATE 1 reconferido depois de `d833f8c`:
  `uv run pytest -m dumps tests/test_pipeline_fidelity.py tests/test_pipeline_tables_v1.py tests/test_pipeline_tables_v2.py tests/test_pipeline_semantics.py -q`
  → `13 passed, 35 deselected in 131.45s`.
- `uv run pytest tests/test_historical_xval.py tests/test_historical_replay.py -q` → 10 + 10 passed.

## REQUEST (lead β) — SPEC v0.2

O núcleo não mudou de semântica, e §3.2 confere com o código, inclusive a ordem de saída de `top1`. Os pontos abaixo são
correções ao SPEC.

1. **§4.6, regra 3 (`occ`): incorreta como está escrita.**
   - *Contraexemplo (hypothesis).* Uma entidade (`Id` 1, `es` 0,60) tem `A01` 0,30 e os traços HYPOTHETICAL 0,55 e
     HYPOTHETICAL 0,62. O contraste é V1 → `icd_thr` 0,30 e `occ` `first_upsert`, no espaço CM.
   - `first_upsert` fica com o primeiro score (0,55, o que satisfaz `valid_trait`); `last_upsert` e `per_entity_any`
     ficam com o último (0,62, que reprova). A regra certificava `occ`.
   - *Correção em `semantics.py`.* A regra também exige que nenhuma entidade relevante repita um nome de traço com
     scores diferentes.
   - *Texto proposto.* "…e cada um desses `Id` pertence a uma única entidade, **sem nome de traço repetido com scores
     diferentes**."
   - Não há caso real (0 entidades em V1 e V2), mas `add_trait` (§4.5) pode criar um.
2. **§3.2, passo 3: "primeira aparição do seu grupo de `Id`".** No código é a do **primeiro candidato** do grupo. Uma
   entidade sem conceitos não posiciona o grupo. Proposta: "na ordem do primeiro candidato do grupo".
3. **§3.2, passo 4: nome de traço repetido dentro de uma entidade.** O código usa o primeiro score em `first_upsert` e
   o último em `last_upsert` e `per_entity_any`. Convém dizer isso explicitamente (é o que torna o item 1 possível).
4. **§3.2, passo 3:** a nota "a docstring de `_select` diz emission order" ficou obsoleta com `d833f8c`.
5. **`oracle/dummies.py`:** o contorno da regra 2 agora é redundante (`semantics.dummy` já tem a condição de ordem).
   Pode ficar ou sair; o resultado é o mesmo.

## Decisões de semântica híbrida (fixadas em `catalog.py`)

- `occ=per_entity_any` com `sel=all`: um registro por (Id da entidade, código).
- `sel=top1`: por grupo de `Id`; os vencedores saem na ordem do primeiro candidato do grupo.
- `occ=first_upsert`: a primeira ocorrência define os escalares e os scores de traço.
- `map=who_exact`: sem fallback de prefixo. `cm_ungated` no espaço OMS: códigos sem projeção vão para `unmapped`.

## Desvios registrados

- **Tamanho do dev (D4 efetivo).**
  - dev: 461 grupos / 1.082 medicamentos (261 forçados + 200 sorteados);
  - cal: 200 / 286;
  - test: 600 / 822;
  - reserve: 3.826 / 5.257.
- **Repetibilidade de 2024.** 15 de 193 grupos diferem no nível 2, todos só na ordem de `Attributes`.
- **Nível 1 "como despejado".** O texto do dump é a re-serialização do MySQL.
- **xval estrita 0/100.** O `link` não tem `ORDER BY`, e a causa da ordem diferente no esquema reduzido não foi
  determinada (relatório §7.3).

## Perguntas / BLOCKED

(nenhuma)
