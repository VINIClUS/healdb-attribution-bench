# Estudo A — Reconstrução histórica (rascunho)

Estudo descritivo do protocolo v0.2 (§3, marco P0). Caracteriza o que está preservado, o que é rederivável e os
limites da reconstrução das versões V1 e V2 do HealDB. **Não faz afirmações causais sobre a transição V1→V2.**

- **Fonte dos números.** Todo número abaixo vem de código versionado neste repositório. Os agregados gerados estão em
  `docs/estudo_a/*.json`; os estados de cada afirmação estão em `repro/claims_study_a.yaml`.
- **Regenerar.**
  - `uv run python -m habench.historical.text_v1`
  - `uv run python -m habench.historical.study_a`
  - `uv run python -m habench.historical.dumps_identity`
  - `uv run python -m habench.historical.sources build`
  - Testes: `uv run pytest -m dumps tests/test_pipeline_*.py tests/test_historical_*.py`.
- **Escopo.** Repetibilidade, tradução e o contraste no corpus inteiro incluem medicamentos dos grupos de teste. Esses
  números são descritivos (desvio D2). O contraste também é reportado só para dev+cal.

## 1. Artefatos e identidade das fontes

- **Manifesto.** `repro/sources_manifest.json` registra:
  - os 9 arquivos do REDU (`10.25824/redu/24I1FH`): o md5 declarado foi recalculado e confere em 9 de 9;
  - o sha256 dos 21 dumps `.sql` usados;
  - os blobs git dos scripts NLP em `405a10c` e `8ea0479`;
  - os hashes dos relatórios F1/F2 e do protocolo.
- **V1 = OpenSource 0605.** Os 33 `.sql` da V1 (20250711) são iguais aos do OpenSource 0605 depois de remover a linha
  `-- Dump completed on`. Nenhum é igual byte a byte (`dumps_v1_0605.json`). Confirma F2 §1.
- **A V2 do depósito mantém os arquivos da V1.** Os 4 arquivos da V1 constam nas versões 1 e 2 do dataset. A
  pertinência a cada versão vem da saída registrada da API do REDU; nenhuma chamada nova foi feita.
- **Proveniência por chamada.** Nas três execuções do ACM (2024, V1, V2), 7.447 de 7.447 respostas têm `ModelVersion`,
  `RequestId` e data HTTP. Os RequestIds são distintos, e nenhum se repete entre execuções.
- **Igualdade de nível 1.** O "arquivo bruto" de `ds_api_response` é a re-serialização do MySQL gravada no dump, não os
  bytes que o ACM devolveu.

## 2. Rederivação das tabelas

O núcleo do pipeline (`src/habench/pipeline/`) é uma reimplementação limpa, parametrizada, das etapas pós-ACM. Com o
preset V1 ou V2, ele reproduz as tabelas históricas a partir das respostas armazenadas.

| Versão | Tabela | Linhas | Resultado |
|---|---|---|---|
| V1 | `entity` | 274.010 | igual em todas as colunas e na ordem da PK |
| V1 | `trait` | 469.957 | igual |
| V1 | `hd_medication_disease` | 43.194 | igual, ids 1..43.194 incluídos |
| V1 | `hd_medication_disease_extend` | 44.233 | igual, ids 23.302..67.534; **regra inferida** (F1 §2.4) |
| V2 | `entity_icd` | 375.595 | igual |
| V2 | `entity_trait` | 107.543 | igual |
| V2 | `cutoff_audit` | 75.119 | igual (sem `dt_created`) |
| V2 | `hd_medication_disease` | 27.861 | igual, atributos incluídos; 0 empates no `GROUP_CONCAT` |

- **Funil V1 (F1 §2.3).** 274.010 → 265.587 (portão da hierarquia) → 259.198 (traços vetados) → 171.713 (HYPOTHETICAL
  > 0,65) → 43.194 (escores ≥ 0,6) → 43.194 (`valid_trait`). Sem o portão (`extend`): 267.392 → 177.839 → 44.233.
- **Regra de HYPOTHETICAL.** A regra documentada no cabeçalho do código ("aceita só com score ≤ 0,6") não reproduz a
  md: daria 39.319 pares e perderia 3.875 pares da V1. A regra executada é o veto acima de 0,65 que está no código.
- **Diferença de 1 ULP (F1 §3.3).** Não aparece na rederivação em Python, porque o texto decimal do dump e o JSON da
  resposta dão o mesmo double. Segundo F1, ela surge só quando o MySQL recarrega o JSON. O replay SQL que testa isso
  está preparado em `scripts/replay/` e ainda não foi executado; `repro/replay_manifest.json` virá dele.
- **O que isso é e não é.** É uma rederivação das semânticas do código público, não uma execução do código
  histórico. O replay SQL do código `405a10c` sem modificação fica registrado à parte.
- **Sistema de codificação da md V1.** 38.132 dos 43.194 códigos têm ponto (CID-10-CM). Só 23.301 (53,9%) existem
  exatamente na hierarquia CID-10 do HealDB. A md V2 guarda CID-10/OMS sem ponto.

## 3. Texto enviado ao ACM

- **Reconstrução da V1.** `(P + s + "\n\n" + H + s)[:10000]`, com `s = ds_indication_eng.strip()`. Bate com todos os
  trechos com posição: 235.557 de 235.557 trechos, em 7.189 respostas. Cobre só 36,95% dos caracteres.
  - **Estado:** `inferido_compativel`.
  - **Sem verificação:** as 258 respostas sem entidades.
  - **Alternativas refutadas:** a indicação crua bate em 0 respostas (78 trechos); a indicação uma só vez, em 8
    respostas.
- **Controle do método na V2.** `ds_text_submitted` bate em 119.302 de 119.302 trechos. Em nenhuma das 7.447 linhas
  ele é igual à reconstrução da V1.
- **Fases (datas HTTP; uma lacuna > 1 h separa fases).**
  - V1: 7.427 / 18 / 2 respostas. Os 20 textos com mais de 10.000 caracteres são os das fases 2 e 3.
  - V2: A = 7.016, B = 431.
  - Execução de 2024: uma única fase.
- **Estabilidade da tradução.** `ds_indication_eng` é igual em 0327 e na V1 para 7.471 de 7.473 medicamentos. As
  exceções são 3205 e 4139.
- **Versões do modelo.**
  - 2024: `2.7.0.20231001`
  - V1: `3.0.0.20231001`
  - V2: `3.2.0.20251001`

## 4. Repetibilidade do ACM dentro de uma execução

Comparação em igualdade de nível 2: a resposta sem o `ResponseMetadata` de topo, com arrays na ordem original. Só
entram textos submetidos idênticos dentro da mesma execução. O limite superior é unilateral de 95%
(Clopper–Pearson) sobre a fração de grupos com alguma diferença.

| Execução | Texto (estado) | Grupos | Medicamentos | Pares | Grupos diferentes | Limite 95% |
|---|---|---|---|---|---|---|
| V1 | reconstruído (`inferido_compativel`) | 197 | 600 | 1.554 | 0 | 1,51% |
| V2 | `ds_text_submitted` (`armazenado`) | 319 | 909 | 1.937 | 0 | 0,93% |
| 2024 | EN cru (`inferido_compativel`) | 193 | 591 | 1.547 | 15 (24 pares) | 11,7% |

- **As 15 diferenças de 2024** estão todas só na ordem do array `Attributes` de alguma entidade. Entidades,
  conceitos, escores e traços são idênticos, e os atributos não entram no pós-processamento.
- **V1 e V2.** Todos os grupos com repetição estão dentro de uma única fase: V1, fase 1; V2, 307 grupos na fase A e 12
  na fase B.
- **Leitura.** Nas execuções observadas, não há variabilidade das respostas sob texto fixo que afete as associações.
  Isso não se estende a outras versões do serviço nem a outras janelas. Com esses dados, H2/L3 não pode ser
  exercitada historicamente (§9.5).

## 5. Variabilidade da tradução

Textos em português idênticos (normalização NFC, espaços, casefold), no universo de 7.447 medicamentos:

- **Grupos.** 516 grupos com português repetido reúnem 1.890 medicamentos. Em 471 deles há mais de uma tradução
  inglesa distinta.
- **Distância de edição por caractere** entre as variantes (2.658 pares): mediana 30, p90 99, máximo 3.838. Na forma
  normalizada, mediana 0,075 e p90 0,20.
- **Português cru após `strip()`.** 469 grupos, 420 com traduções distintas.

A tradução armazenada é o único registro: serviço, modelo e parâmetros não foram guardados.

## 6. Contraste real "pós-processamento V1 → V2" nas mesmas respostas V1

Bundle `V1_TO_V2`, com D = {`ent_thr`, `icd_thr`, `map`, `occ`, `sel`, `trait`}. São 64 híbridos no espaço CID-10/OMS;
a saída CID-10-CM é projetada por correspondência exata mais fallback, uma projeção estrutural (§5.1).

| Escopo | Chaves V1 | Aparecem | Somem | Famílias com 1 / 2 / 3 / 4 / 5 conjuntos | Não monótonas |
|---|---|---|---|---|---|
| dev+cal | 11.669 | 6.862 | 6.503 | 8.699 / 3.676 / 946 / 44 / 0 | 1.302 |
| corpus inteiro (descritivo, D2) | 34.101 | 27.405 | 18.284 | 27.874 / 14.182 / 3.464 / 168 / 1 | 4.555 |

- **Participação em algum conjunto mínimo (corpus inteiro).**
  - `sel`: 23.425
  - `occ`: 18.859
  - `trait`: 17.561
  - `icd_thr`: 12.784
  - `ent_thr`: 2.287
  - `map`: 0

  O portão da V1 e o descarte NO_MAP da V2 são o mesmo predicado, então `map` é um fator naturalmente sem efeito no
  espaço OMS.
- **Tabelas-verdade distintas entre as associações que mudam:** 285 (dev+cal) e 487 (corpus inteiro).
- **Limites.**
  - Os híbridos intermediários não têm execução histórica: são contrafactuais do pipeline rederivado.
  - A cobertura por oráculo SQL histórico é parcial (seção 7).
  - A transição histórica também mudou o texto submetido e o modelo do ACM. Este contraste isola só o
    pós-processamento sobre respostas fixas.

## 7. Replay SQL e validação cruzada (pendente)

- **O que está preparado.** Os scripts de `scripts/replay/` sobem um MySQL 8.0.33 descartável (`healdb-replay-*`, senha
  de `HAB_MYSQL_PASSWORD`). Eles executam `process_disease_data_json` e `link_medications_with_diseases` de `405a10c`
  sem modificação e exportam `entity`, `trait` e md.
- **Validação cruzada.** Cerca de 100 híbridos do subreticulado exprimível na V1 (limiares, regras de traço, portão),
  só com medicamentos de dev, comparados com o núcleo.
- **Tabela de cobertura.** Mostra quais células de fator têm oráculo SQL histórico:
  `uv run python -m habench.historical.xval coverage`.
- **Resultados.** Entram aqui e em `repro/replay_manifest.json` depois da execução pela sessão principal.

## 8. Limitações

- **Nível 1.** O texto bruto é o do dump, não o recebido do ACM.
- **Texto da V1.** É inferido, não provado idêntico; o cabeçalho H e o separador só são verificados pelo comprimento.
- **`extend`.** A regra, a busca na hierarquia e o primeiro id foram ajustados aos próprios dados.
- **Não reexecutado neste pacote.**
  - A leitura das fases da V1 (textos longos falhando na fase 1).
  - O bug de backspace no SQL da V2 (F1 §4.6).
- **Exposição do corpus.** O corpus inteiro já tinha sido examinado no planejamento (D2). Os números do corpus inteiro
  são descritivos e não entram no conjunto confirmatório.
