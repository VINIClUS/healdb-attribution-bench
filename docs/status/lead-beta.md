INTERFACE READY: 2d9f06b
INTERFACE CHANGE: `truth.build_truth` — o callback `dummy` passa a ser `dummy(hybrids, key, f)` (padrão
`oracle.dummies.certificate`); `expressible(cell, hybrids, S)` tem padrão N1/N2 (SPEC 7.1); novo `recorded=` opcional.

# Status — Lead β

## Estado

β3 em andamento. SPEC v0.2 aprovado na GATE 2 (`docs/decisoes.md`). As interfaces compartilhadas com o lead γ estão
commitadas em 2d9f06b.

## Interfaces para o lead γ (estáveis)

- `habench.oracle.contrast`
  - `Contrast` (SPEC §5.1): grupo, meds, espaço (`"who"`/`"cm"`), x0/x1 executados, d0/d1 declarados, `D`, variantes
    `variants0/1` (só os fatores `alt`), `patches` (`pipeline.evidence.Patch`), `bundles`, `prep_available`.
  - `make_contrast(...)` deriva `D` e põe `patch:<id>` False/True em x0/x1. `validate()` levanta `SealedError` para
    grupo de teste.
  - `to_json`/`from_json`, `canonical()`, `content_hash()` (SHA-256 do JSON canônico).
- `habench.oracle.hybrids.Hybrids(contrast, evidence, hier, levels="executed"|"declared", prep_evidence=...)`
  - Métodos `D`, `admissible(S)`, `config(S)`, `run(S, trace=)`, `state(S, key)`, `truth_table(key)`, `runs`,
    `endpoints_reproduce()`.
  - Um run por `S` para o grupo inteiro, com cache pela configuração realizada. As variantes `alt` são realizadas
    como níveis do núcleo (`realize`).
- `habench.oracle.truth`
  - `CellSpec.of(view, capability)`; views `L1`, `L2-R`, `L2-M`, `L3-R`, `L3-M`, `N1`, `N2` e ablações
    `<base>-A1…A6`/`-C1…C4`.
  - `Identification(W_lo, W_hi, saturated).state`.
  - `QueryTruth`: `cell(view, capability)`, `F_star`, `F_adm`, `sufficient(S)`, `is_dummy(f)`, `table`.
  - `ContrastTruth`: `origin`, `necessity[(view, cap)]`, `budget_abstention_appropriate`, JSON.
  - `build_truth(hybrids, queries, partition=, scenario_family=, cells=, ident=, dummy=, declared_hybrids=,
    expressible=)`; `write_truth`/`read_truth` (nunca para `test`).
  - O `origin` semissintético só existe aqui.
- Apoio: `habench.oracle.families` (`analyze`, `naive_family`, `reference_bfs`, `necessity`),
  `habench.oracle.dummies.certificate` (regras de 4.6 com a condição de ordem da regra 2) e `habench.oracle.toy`
  (hierarquia e respostas de brinquedo para testes).

## Feito

- β1 e β2 (SPEC v0.2 aprovado).
- β3, interfaces: `oracle/{contrast,hybrids,families,truth,dummies,toy}.py` e `tests/test_oracle_*.py`, incluindo o
  teste diferencial de famílias (A19, parte 1): DP × O(3^n) × BFS, com inadmissíveis e dummies, em hypothesis.

## Em andamento

- `oracle/{universe,identify}.py` (spike com |D| = 6 em L1).

## Próximo

- `eval/{score,metrics,stats,precision_sim}.py`.
- A15: medição da expansão de U.
- A19 parte 2: `pipeline.core` × núcleo de força bruta.

## Testes

- `uv run pytest -q` → `539 passed`

## Perguntas / BLOCKED

Nenhum.

## REQUEST (lead α)

1. **Defeito na regra 2 de `semantics.dummy`** (`semantics.py:126-129`, SPEC 4.6, EX-30). Falta a condição de ordem.
   O oráculo contorna o defeito em `oracle/dummies.py`.
2. **Docstring de `core._select`**: diz "in emission order", mas a ordem é a da primeira aparição do grupo de `Id`.
3. Um teste de solidez por propriedade das regras dummy, com `Id` duplicado.
