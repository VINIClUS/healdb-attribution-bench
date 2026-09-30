DONE: β3 — com as exceções de cobertura listadas em "Não coberto" (células ficam fora da verdade; `QueryTruth.cell`
levanta `KeyError`) e uma pergunta aberta (BLOCKED abaixo) que não afeta as interfaces do lead γ.
BLOCKED: SPEC §8 não define as histórias E0/E1 de contrastes com patch (`patch:*` em D) em células sem a resposta
completa (L1 e top-1: A2/C2/C4). Proposta, **não implementada**: declarar essas células "n/a estrutural" para
contrastes com patch, porque a view não expõe o handle do patch. Hoje elas ficam fora da verdade
(`NotImplementedError` em `oracle/reference._unsupported`). Pede decisão da sessão principal.
INTERFACE READY: 2d9f06b
INTERFACE CHANGE: `truth.build_truth` — o callback `dummy` passa a ser `dummy(hybrids, key, f)` (padrão
`oracle.dummies.certificate`); `expressible(cell, hybrids, S)` tem padrão N1/N2 (SPEC 7.1); novo `recorded=` opcional.

# Status — Lead β

## Estado

β3 concluído (HEAD 14b2708). SPEC v0.2 aprovado na GATE 2 (`docs/decisoes.md`). As interfaces compartilhadas com o
lead γ estão estáveis desde 2d9f06b, com a mudança compatível registrada acima.

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
    expressible=, recorded=)`; `write_truth`/`read_truth` (nunca para `test`).
  - O `origin` semissintético só existe aqui.
- Identificação: `habench.oracle.reference.ident_fn(contrast, group_ev, hier, UniverseCache(...))` é o callback
  `ident=` de `build_truth`. Uma célula não coberta levanta `NotImplementedError` e fica fora da verdade.
- Avaliação: `habench.eval.score.score_query(truth, qid, raw, cell, budget=, log=)`; `habench.eval.metrics`
  (`primary`, `secondary`, `per_class_prf`, `set_metrics`, `stability`, `costs`, `stratify`); `habench.eval.stats`
  (`paired_cluster_bootstrap`, `ni_pvalue`, `sup_pvalue`, `holm`, `p_h2`, `clopper_pearson_*`, `committed_risk`,
  `h1b_guard`, `noninferiority`); `habench.eval.precision_sim.simulate_power`.
- Apoio: `habench.oracle.families` (`analyze`, `naive_family`, `reference_bfs`, `necessity`),
  `habench.oracle.dummies.certificate` (regras de 4.6 com a condição de ordem da regra 2) e `habench.oracle.toy`
  (hierarquia e respostas de brinquedo para testes).

## Feito (β3)

- Interfaces `oracle/{contrast,hybrids,truth}.py` (2d9f06b), `families.py`, `dummies.py`, `toy.py`.
- Identificação (SPEC 8):
  - `oracle/identify.py`: observações por componente, W_lo por lifting, W_hi marginal, estado (8d70324).
  - `oracle/universe.py`: hipóteses (≤ 3 desvios), alfabeto simbólico, bundles com L ≤ 4, avaliação em lote,
    expansão BFS com orçamentos, `symbolize`, `lift_doc`, view top-1 (7330d48, aed5bfe).
  - `oracle/reference.py`: escolha do universo por célula e memo `UniverseCache`.
  - Spike (`oracle/spike_universe.py`) e medição A15 (`oracle/a15_measure.py`).
- `eval/score.py`: validação 9.1, lastro 9.2 (passo 0, cobertura módulo dummies) e tabela total com precedência;
  todas as células estado × verdade testadas (2c993be).
- `eval/metrics.py`, `eval/stats.py`, `eval/precision_sim.py`, conferidos contra scipy (2ebc3d7).
- A19 (73e71e6 e testes de famílias):
  - DP × O(3^n) × BFS: hypothesis com inadmissíveis e dummies; nenhuma discrepância.
  - `pipeline.core` × núcleo de força bruta do SPEC: hypothesis, 600 exemplos; presença e conjunto de registros
    reprovados por registro. **Nenhuma discrepância.**
- A15: memo por assinatura simbólica e orçamento por consulta (14b2708). Números abaixo.

## A15 — custo da expansão de U (dev)

Configuração: contraste V1 → V2 por componentes, espaço WHO, 3 grupos dev sorteados (semente 20260930), 2 consultas
alteradas por grupo, `--L 2 --max-dev 1 --budget 60`. Comando:
`uv run python -u -m habench.oracle.a15_measure --groups 3 --queries 2 --L 2 --max-dev 1 --budget 60`.

Por expansão calculada (as demais vieram do memo):

| chave | modo | hipóteses | alfabeto (entidade × conceito) | L=1 | L=2 | corte | runs do núcleo | s |
|---|---|---|---|---|---|---|---|---|
| G98 | l1 | 11 | 60 × 10 | 600 bundles, 25 classes, 1,1 s | 15.250 bundles, 651 classes, 53,6 s | L=2 atingido com classes novas | 1.408 | 54,8 |
| G98 | top1 | 8 | 60 × 10 | 600 bundles, 263 classes, 1,1 s | não avaliado | orçamento de bundles (99.430 projetados > 50.000) | 512 | 1,3 |
| R093 | l1 | 11 | 60 × 5 | 300 bundles, 25 classes, 0,5 s | 7.625 bundles, 565 classes, 24,8 s | L=2 atingido com classes novas | 1.408 | 25,4 |
| R093 | top1 | 8 | 60 × 5 | 300 bundles, 263 classes, 0,4 s | parcial | orçamento de tempo em L=2 | 832 | 79,8 |

- **Memo por assinatura simbólica** (`universe.signature`): alfabeto sem os códigos e comportamento de cada código
  do pool, posição a posição. As testemunhas são renomeadas para o pool da chave nova.
  - 12 expansões pedidas, 4 calculadas, 8 acertos no memo (K11, J98 e B96 → G98; A498 → R093).
  - Tempo total de 436 s sem o memo por assinatura para 170 s com ele, com resumo por célula idêntico.
  - Por contraste: 59 s, 108 s (11 meds) e 2 s (só acertos).
  - Teste: `test_memo_by_symbolic_signature` (mesmas classes que uma expansão fresca e testemunhas renomeadas
    reproduzem a classe).
- Custo de uma expansão l1 em L=2: cerca de 55 s com 10 símbolos de conceito, cerca de 25 s com 5.
- Saturação: nenhuma expansão saturou em L ≤ 2. Como o corte vale "não saturado", nenhuma célula sem a resposta
  completa chega a `identificado`.
- O orçamento de tempo é checado entre lotes e estoura um pouco: 79,8 s contra 60 s.
- L = 3 ou max-dev ≥ 2 não terminam em tempo útil. No spike: 149 hipóteses e 98.210 bundles em L=2, com corte.

Estados por célula (6 consultas):

| célula | estados | saturadas | média \|W_hi\| |
|---|---|---|---|
| L1 × R-C | ambiguo 5, indeterminado 1 | 0 | 27,2 |
| L2-R × R-C | identificado 5, indeterminado 1 | 6 | 1,17 |
| L2-M × R-C | identificado 6 | 6 | 1,0 |
| L2-R-A3 × R-A | identificado 5, indeterminado 1 | 6 | 1,17 |
| L2-R-A2 × R-C | indeterminado 6 | 0 | 3,5 |

- **L1 `indeterminado` (G98, grupo de 1 med): limitação do lifting, erro na direção conservadora.**
  - Os conceitos de `a` (G98.8) são o conceito de topo de entidades que também têm G96.9/G96/G99.
  - Ao removê-los, G96/G969 sobem ao topo e aparecem no grupo levantado. Por isso o lifting é rejeitado e
    W_lo = {F*}, com |W_hi| = 26.
  - W_lo continua um limite inferior correto: o erro é perder `ambiguo`, nunca afirmar algo falso.
- **L2-R `indeterminado` (R093, grupo de 11 meds): comportamento previsto pelo SPEC.**
  - A hipótese `occ` alt no run 0 reproduz a observação marginal de `a` com família {icd_thr, trait}.
  - Ela muda, porém, os finais de outras meds (2954, 6246, 5159). Assim entra em W_hi (marginal) e não em W_lo
    (grupo).
- L2-R-A2: o nível L=2 do top-1 não foi avaliado (orçamento), então 0 saturadas e 6 `indeterminado`.

## Não coberto (célula fora da verdade)

Em todos os casos abaixo, `NotImplementedError` → `build_truth` omite a célula.

- Contrastes com patch sem a resposta completa: SPEC omisso, ver BLOCKED.
- Lacunas de implementação (o SPEC é explícito):
  - expansão sobre bundles ou fatores de prep;
  - replay declarado sobre bundles expandidos (sem code link com R-A/R-B, por exemplo C4 × R-A);
  - componente de trace sobre bundles expandidos (L2-M/L3-M com A2).
- Simplificações declaradas de U:
  - Ids distintos dentro dos bundles (`symbolize` devolve None para Id duplicado);
  - classes de trait fundidas pelo comportamento de uma entidade só;
  - o lifting remove os conceitos de `a` de todas as entidades, o que pode falhar como no caso G98.

## Testes

- `uv run pytest -q` → `647 passed, 40 deselected`.

## REQUEST (lead α)

1. **Defeito na regra 2 de `semantics.dummy`** (`semantics.py:126-129`, SPEC 4.6, EX-30). Falta a condição de ordem.
   O oráculo contorna o defeito em `oracle/dummies.py`.
2. **Docstring de `core._select`**: diz "in emission order", mas a ordem é a da primeira aparição do grupo de `Id`.
3. Um teste de solidez por propriedade das regras dummy, com `Id` duplicado.
4. O oráculo usa funções privadas de α: `semantics._variants`, `core._code_map` e `core._select` (em
   `oracle/dummies.py`). Pedido: mantê-las estáveis ou torná-las públicas.
