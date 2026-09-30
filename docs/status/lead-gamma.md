# Status — lead γ

## Estado
Onda (a) em andamento: contrato de métodos e `Env` de tabela prontos; workers de busca, isolamento e BugDoc lançados.

## Feito
- `src/habench/methods/base.py`: protocolos `Env`/`Method` (SPEC §11.1), `Explanation`, `Certificate`, `Query`,
  `EvalResult` com traço em dados simples (`TraceRecord`, sem tipos de `habench.pipeline`), `Unavailable(reason)`
  com motivos `inadmissible` / `no_replay` / `not_expressible` / `not_visible`, `BudgetExhausted`, validação EX-23.
- `src/habench/env/table.py`: `Ledger` (regras de orçamento e cache de §7.4, compartilhadas com o broker) e
  `TableEnv` (dublê por tabela-verdade).
- `tests/test_env_contract.py`: contrato de §7.3/§7.4 parametrizado por implementação de `Env` (o broker T11 entra
  na mesma lista).

## Em andamento
- T12 `methods/search.py` (worker), isolamento `views/isolation.py` (worker), T15 `methods/bugdoc_adapter.py` (worker).

## Próximo
- T14 B3, B0/B1/B2 contra o `TableEnv`.
- (b) após as interfaces do β em main: T10 vistas, T11 broker, T9 cenários.
- (c) T13 M, T21 runner.

## Testes
- `uv run pytest -q tests/test_env_contract.py tests/test_methods_base.py` → 24 passed.

## Números re-derivados
(nenhum ainda)

## Perguntas / BLOCKED
(nenhuma)

## Desvios propostos
- `Explanation` ganhou o campo `notes: tuple[str, ...]` (não pontuado), para registrar família parcial e motivos de
  invalidação. O esquema de §11.1 fica intacto nos demais campos.

## REQUEST
(nenhum)
