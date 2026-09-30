# Status — lead γ

## Estado
Onda (a) concluída; (b) em andamento (vistas prontas; broker/RPC e cenários com workers); M (T13) escrito;
falta T21 runner e o teste de ponta a ponta de M contra o oráculo.

## Feito
- `methods/base.py`: contrato `Env`/`Method` (SPEC §11.1), `Explanation`/`Certificate`/`Query`, `EvalResult` com
  traço em dados simples (`TraceRecord`), `PresenceMap` (UNAVAILABLE por medicamento, §1.4), `Unavailable(reason)`
  (`inadmissible`, `no_replay`, `not_expressible`, `not_visible`), `BudgetExhausted`, validação EX-23.
- `env/table.py`: `Ledger` (orçamento, cache, handles inertes, recusas de §7.3/§7.4 — o broker reusa) e `TableEnv`.
  `tests/test_env_contract.py`: contrato parametrizado por implementação.
- T12 `methods/search.py`: BFS de referência (§6.3), conjunta, poda por dummy, completude sobre inadmissíveis.
  Testes: EX-16, EX-28 (a/b), propriedade contra referência ingênua O(3^n), e **igualdade com
  `oracle.families.reference_bfs` do β** (avaliações, famílias, completude, esgotamento).
- B0, B1, B3 (`methods/b0.py`, `b1.py`, `b3.py`); B2 depende das vistas materializadas (próximo).
- T15 `methods/bugdoc_adapter.py`: Stacked Shortcut standalone vendorizado. Fidelidade: testes upstream passam
  (subprocesso); Exemplo 1 do artigo recupera `{LibraryVersion=2.0}` com **2** execuções (a linha que duplica CPg é
  memoizada pelo código); Teoremas 1 e 2 como propriedades; Teorema 5 **falha** no código vendorizado
  (`xfail(strict)` com contraexemplo: k=2, falha = (p0=0) ∨ (p0=1 ∧ p2=2), CPf=(0,0,2,0,0); o código nunca
  restaura `cf` entre instâncias boas). Diferença semântica documentada no módulo ("causa definitiva" do BugDoc ×
  "suficiente no contexto x0" do SPEC).
- Isolamento `views/isolation.py`: audit hook (arquivos fora da vista, verdade, código dos módulos proibidos,
  sockets, subprocessos, ctypes, escrita fora de scratch; imports de pipeline/oracle/scenarios) e `scan_leaks`
  (nomes e conteúdo descompactado gz/zip). Achados: import em cache não dispara o evento `import` (por isso
  `install` recusa se um módulo proibido já foi carregado); um `Pipe` criado antes do hook continua funcionando.
- T10 `views/layout.py` (ids HMAC, manifest, lado do broker na verdade), `views/profiles.py`, `views/build.py`,
  `repro/evidence_views.yaml`: cadeia byte a byte L1 ⊂ L2-R ⊂ L2-M, ablações A1–A6, C1–C4, mtimes constantes,
  ordem embaralhada, varredura de vazamento.
- T13 `methods/m.py` + `methods/evidence_rules.py` (escrito pelo lead): inventário; declarado × executado (com
  vínculo: comparação; sem vínculo: hipóteses testáveis de divergência de nível de §4.3, `on`/`off`, ≤ 3, filtradas
  pelos finais e pelos traços armazenados); BFS conjunta por hipótese; regras dummy corretas e incompletas do lado do
  método (regra 0 para patches, regra 1 em faixa fechada); regras de irrelevância de par/variante; saída consciente
  de identificação (`alternativas` quando hipóteses consistentes dão famílias distintas); sem replay, V só quando
  `final` + `dummy` cobrem o reticulado. Botão `rigor` (`strict`/`lenient`) para a calibração em cal (§13.5).
  Testes: EX-07, EX-11 (sem vínculo → `alternativas` com 2 famílias; com vínculo → V; L2-M−A3 → traço refuta a
  história declarada → V), EX-12 em R-C com dummy, faixa HYPOTHETICAL oculta, orçamento, replay inválido,
  inadmissível.

- T11 `env/broker.py`, `env/child.py`, `env/rpc.py`: `BrokerEnv` (réplica com níveis executados com vínculo e
  declarados sem ele; A2 sobre evidência top-1; handles opacos de patch; handles inertes; `Ledger`), N1/N2 via
  `oracle.truth.default_expressible` do β (a mesma regra da necessidade da verdade), RPC por processo filho `spawn`
  com o hook instalado antes de importar o método, `__main__` vazio no filho. Falha, travamento ou timeout do
  filho → `falha_de_execucao` em todas as consultas.
- B2 `methods/b2.py`: primeira divergência (resposta → registros do traço → estágio do núcleo), candidatos
  `noncausal`; sem traço, degenera em B1.
- M: guarda de hash (respostas diferem sem handle de evidência visível → nunca V, inclusive `lenient`);
  `MLenient` para a varredura de rigor em cal.
- T21 `runner/matrix.py`, `runner/batch.py`, `runner/__main__.py`: matriz eficiente (n/a L1 × R-A/R-B;
  equivalências R-B ≡ R-A sem prep e L3 ≡ L2), lote retomável (verdade, vistas, execuções; recusa verdade velha
  pelo `contrast_hash`), saídas em `runs/<partição>/<lote>/<cid>/<vista>__<cap>__b<orç>__<método>.json`.
- Aceitação (`tests/test_runner_acceptance.py`): M = oráculo em L2-M × R-A, orçamento ilimitado, em 9 contrastes
  de brinquedo (EX-07, 08, 09, 10, 11, 14 componentes e bundle, occ×sel no espaço CM, map), via construtor de vistas
  e broker reais; todo certificado verdadeiro na tabela-verdade, `eval` só do log, cobertura §9.2 passo 3 satisfeita.
  Os 6 métodos rodam isolados sem `falha_de_execucao`.

- T9 `scenarios/` + `repro/scenario_catalog.yaml`: famílias N (a, b), F (com patches de borda), M (com `EXTEND` no
  espaço CM), O, X (i, ii com cotas de forma, iii só dev/cal), I (divergência declarado × executado e execuções que
  realizam `alt`); P, N(c) e N(d) só catalogados. Validadores das invariantes de §4.5; amostragem ≤ 25/25 com
  probabilidades de inclusão; ids opacos; `test` → `SealedError`; `test_levels()` → `SealedError` até o
  congelamento. Smoke do worker (3 grupos dev, `-m dumps`): 94 cenários (N 9, F 21, M 14, O 15, X 18, I 17), 0 erros
  de geração.
  - Definições adotadas para X(ii) (SPEC linha 1146 não as fixa): "sem efeito verificado" = dummy verdadeiro em
    todas as consultas alteradas amostradas; "par oposto" = f, g com state({f}) ≠ state(∅) e state({f,g}) =
    state(∅) numa consulta amostrada. Todo X(ii) é semissintético (leva um patch de cancelamento).
  - I(c): x0 = x1 em nível, com `variants1` (o diff declarado fica vazio).

## Em andamento
- Smoke de 5 grupos dev (`uv run pytest -m dumps tests/test_runner_smoke.py`).

## Próximo
- Revisar T9; smoke de 5 grupos dev (`-m dumps`) com matriz reduzida; aceitação de M sobre cenários reais.

## Why-Diff (opcional): não implementado
- Não há código público (ver `docs/design/ambiente_e_comparadores.md` §3). O exemplo do artigo (Fig. 7a/8, Tabela 2)
  só existe como grafos renderizados: o texto dá os conjuntos resultantes (EQE, EQA, UEQ, UM2), não as arestas.
  Um teste de fidelidade exigiria reconstruir as arestas a partir das figuras, o que é inferência.
- Pelo §10.1 do protocolo, uma heurística própria não recebe o nome de Why-Diff. O comparador publicado executado
  é o BugDoc. As alegações de superioridade sobre Why-Diff ficam restritas (limitação registrada).

## Testes
- `uv run pytest -q` → 650 passed, 3 xfailed (antes de M); `tests/test_methods_m.py` → 10 passed.

## Números re-derivados
- Exemplo 1 do BugDoc: 2 execuções novas (`uv run pytest -q tests/test_methods_bugdoc.py`).

## Perguntas / BLOCKED
(nenhuma)

## Desvios propostos
- `Explanation.notes` (não pontuado) para inventário, hipóteses e motivos de invalidação.
- B3: quando nenhum singleton é suficiente e algum complemento leave-one-out é suficiente, B3 não procura os
  conjuntos intermediários e responde `informacao_insuficiente` (`ambiguidade`). O desenho §D não fixa esse caso.
- BFS: todo `Unavailable` (inclusive `no_replay`/`not_expressible`) conta como "desconhecido" para a completude
  (leitura conservadora). A poda por dummy nunca esconde um inadmissível no núcleo real, porque a admissibilidade só
  depende dos fatores de preparação e as regras dummy nunca certificam fatores de preparação (regra 0).
- N1/N2: `final` é o mapa de presença com `schema` `md_v1`/`md_v2`, não as linhas históricas de `md`.

## REQUEST
- **REQUEST (lead β):** `oracle.contrast._patch_from` devolve `JsonEdit.value` como `list`/`dict` simples. Os patches
  `add_trait`, `remove_trait` e `swap_entities` usam valores assim, e `Evidence.patched` faz hash do `Patch`, então um
  contraste relido por `Contrast.from_json`/`read_truth` quebra ao aplicar esses patches. Proposta: congelar os
  valores em `_patch_from` (tuplas/`frozendict` canônicos) ou fazer `Patch` ter hash pelas edições canônicas (JSON).
  Contorno atual: `scenarios.patches.freeze_patch`; o runner usa os contrastes em memória, nunca relidos.
- **REQUEST (lead β), confirmar:** em N1/N2 o broker usa agora `oracle.truth.default_expressible` (patches são
  expressáveis). Uma leitura literal da linha 622 do SPEC os excluiria; como a regra é compartilhada, a verdade e o
  broker concordam em qualquer caso.
