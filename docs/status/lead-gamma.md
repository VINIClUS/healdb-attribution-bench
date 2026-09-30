DONE: γ

# Status — lead γ

## Estado
Concluído: T9–T15, T21, isolamento e smoke de 5 grupos dev. M = oráculo em 2026/2026 consultas reais
(L2-M × R-A, b = 64). A matriz completa de dev/cal **não** foi lançada (decisão da sessão principal).

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
(nada)

## Próximo (sessão principal)
- Decidir o lançamento da matriz completa de dev/cal (estimativa abaixo) e o armazenamento das vistas.
- β: pontuação (`eval`) sobre `runs/`; U/identificação (β3) para as células que precisam de U. Hoje o runner chama
  `build_truth` sem `ident`, então essas células ficam fora da verdade até a β3 entrar.

## Why-Diff (opcional): não implementado
- Não há código público (ver `docs/design/ambiente_e_comparadores.md` §3). O exemplo do artigo (Fig. 7a/8, Tabela 2)
  só existe como grafos renderizados: o texto dá os conjuntos resultantes (EQE, EQA, UEQ, UM2), não as arestas.
  Um teste de fidelidade exigiria reconstruir as arestas a partir das figuras, o que é inferência.
- Pelo §10.1 do protocolo, uma heurística própria não recebe o nome de Why-Diff. O comparador publicado executado
  é o BugDoc. As alegações de superioridade sobre Why-Diff ficam restritas (limitação registrada).

## Testes
- `uv run pytest -q` → **759 passed, 0 failed, 3 xfailed**. Os 3 xfail estritos são achados de fidelidade do
  BugDoc: o Teorema 5 falha duas vezes, e o `budget_test.py` upstream precisa de zmq.
- Smoke `-m dumps`: `uv run pytest -q -m dumps tests/test_runner_smoke.py` → **1 passed in 969.73s (0:16:09)**
  (5 grupos dev, em `tmp_path`, métodos m e b3, sem cruzamento de informação; 0 divergências de M;
  log em `/home/vinicius/hab-data/runs/dev/smoke_pytest.log`).

## Smoke de 5 grupos dev (execução registrada)
- Comando: `uv run python -m habench.runner --partition dev --seed 20260930 --max-groups 5 --name smoke5`
  (matriz padrão: b0, b1, b2, b3, bugdoc, m; `info_fraction` 0,2). Saída: `/home/vinicius/hab-data/runs/dev/smoke5.out`;
  progresso: `smoke5.part1.err` e `smoke5.err`.
- A sessão foi interrompida no contraste 66/138 e o lote foi **retomado** com o mesmo comando (retomada
  verificada: nenhuma saída recomputada).
- Resultado (JSON da 2ª parte): `contrasts` 138, `cells_run` 9172, `cells_equivalent` 2774, `errors` 0,
  `m_checked_queries` 2026, `m_mismatches` 0.
- Tempo de parede: 1ª parte ≈ 16 min (contrastes 1–66, pelos horários do log: 3/138 às 15:57:51 e 62/138 às
  16:12:01); 2ª parte 1287 s = 21,5 min (contrastes 67–138, mais a revisita rápida dos 66). **Total ≈ 37 min**,
  serial, 1 processo pai. O CPU da 2ª parte (pai + filhos) foi 1283 s, ≈ parede: o lote é limitado por CPU e serial.
- Pico de RSS: pai 558 MiB; cada filho de método é pequeno (processo `spawn` por célula, ≈ 0,1–0,2 s de parede
  por célula, medido em `tests/test_runner_acceptance.py`).
- Saídas: `/home/vinicius/hab-data/runs/dev/smoke5/<cid>/<vista>__<cap>__b<orç>__<método>.json` (11 946
  arquivos, 29 MiB); vistas em `/home/vinicius/hab-data/views/dev/` (20 710 arquivos, **388 MiB**); verdade em
  `/home/vinicius/hab-data/truth/dev/` (1 550 arquivos, 1,9 MiB).
- Cenários dos 5 grupos: 138 contrastes (≈ 27,6 por grupo).

## Estimativa da matriz completa (A15)
- Base: ≈ 2250 s de parede serial por 5 grupos → ≈ 450 s por grupo com a matriz padrão.
- Grupos (`repro/split_manifest.csv`): dev 461, cal 200.
- Serial: dev ≈ 461 × 450 s ≈ 58 h; cal ≈ 200 × 450 s ≈ 25 h. Com `m_lenient` em cal (varredura de rigor), cal
  sobe ≈ 10–15 %.
- Com 8 CPUs, `--shard i/8` (novo; um processo por CPU, os contrastes escrevem arquivos disjuntos; criar a chave
  HMAC antes, p. ex. rodando uma vez um shard pequeno): ideal ≈ 7,3 h (dev) + 3,2 h (cal) ≈ **10,5 h**; com ≈ 70 %
  de eficiência (carga desigual entre contrastes, E/S das vistas), ≈ **15 h**.
- Ressalvas:
  - os 5 grupos do smoke são pequenos. O custo do núcleo cresce com o número de medicamentos do grupo, então grupos
    maiores podem esticar a cauda;
  - a memória por shard fica ≈ 0,6 GiB (8 shards ≈ 5 GiB, dentro dos 15 GiB compartilhados).
- **Armazenamento é o gargalo.** As vistas extrapoladas ocupam ≈ 388 MiB / 5 grupos → ≈ 36 GiB em dev e ≈ 15,5 GiB
  em cal, dominados pelas vistas da família I, cruzadas com 23 perfis. Opções:
  - vistas por contraste sob demanda, apagadas após as execuções (a verdade guarda o `BrokerSide`, e a reconstrução
    é determinística, byte a byte);
  - ou reduzir `info_fraction`.

## Números re-derivados
- Exemplo 1 do BugDoc: 2 execuções novas (`uv run pytest -q tests/test_methods_bugdoc.py`).
- Custo de `run_isolated` por célula (EX-07, L2-M): b0 0,101 s; b1 0,088 s; b3 0,113 s; bugdoc 0,185 s; m 0,105 s;
  m_lenient 0,112 s (`rtk proxy uv run pytest -q -s tests/test_runner_acceptance.py -k isolated`).
- Aceitação de M em brinquedo: 9 contrastes (EX-07/08/09/10/11/14 componentes e bundle, occ×sel, map), todo
  certificado verdadeiro e cobertura §9.2 (`uv run pytest -q tests/test_runner_acceptance.py`).
- Aceitação de M em dados reais: 2026 consultas elegíveis, 0 divergências (`smoke5.out`, `runner/check.py`).
- Smoke do worker de cenários (3 grupos dev): 94 cenários, 0 erros de geração.

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
