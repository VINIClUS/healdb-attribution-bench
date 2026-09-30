# SPEC — benchmark de atribuição de mudanças por associação (HealDB)

Versão 0.1 (lead β, 2026-09-30), para revisão na GATE 2. Implementa o protocolo v0.2
(`docs/protocolo/Protocolo_Experimental_HealDB_Revisado_v0_2.md`). As resoluções **R01…R30** são as de
`docs/analise/00_analise_protocolo.md` §3.

## 0. Convenções

- **Idioma.** A prosa é em português. Identificadores, nomes de fator, níveis e estados ficam em inglês, exatamente
  como aqui e em `src/habench/types.py`.
- **Exemplos.** Cada exemplo tem um identificador `EX-nn` (semântica) ou `EX-Snn` (pontuação). Os dados completos
  estão em `tests/data/spec_examples.json`, sob o mesmo identificador. `tests/test_spec_examples.py` recalcula cada
  resposta esperada com uma referência de força bruta que não importa `habench`, e confere que os identificadores do
  SPEC e do JSON são os mesmos, nos dois sentidos.
- **Valores dos exemplos.** São didáticos. Um exemplo pode usar níveis fora do catálogo (0,58 em EX-07) e respostas
  com menos de 5 conceitos. Todo valor numérico citado aqui ou em `docs/design/` fica **queimado**: não pode entrar
  na lista selada de níveis de teste (R28).
- **Notação.**
  - `D` é o conjunto de fatores alterados de um contraste; `S ⊆ D` é um subconjunto; `h_S` é o híbrido.
  - `state_S(a) ∈ {present, absent}` é o estado da associação `a` em `h_S`.
  - Uma **família** é um conjunto de conjuntos de fatores, escrita `{{ent_thr},{patch:p1}}`.

## 1. Associações, espaços de comparação e presença (§5.1)

### 1.1 Chave

`AssocKey(med, system, version, code)` (`types.py`):

| espaço | `system` | `version` | `code` |
|---|---|---|---|
| CM | `ICD-10-CM` | `acm:<ModelVersion>` da resposta | código do ACM com ponto, como devolvido (`E11.65`) |
| OMS | `ICD-10-WHO` | `hier:<prefixo sha256 das tabelas de hierarquia>` | código OMS sem ponto, 3 ou 4 caracteres (`E119`) |

Códigos de terminologias diferentes nunca se igualam por remoção de ponto ou truncamento. A passagem CM → OMS é
sempre a projeção declarada abaixo, rotulada "projeção estrutural".

### 1.2 Projeções

Seja `nodot = code.replace(".", "")`, `cat` o conjunto de categorias (3 caracteres) e `subcat` o de subcategorias
(4 caracteres) da hierarquia fixada.

| nível de `map` | chave produzida | quando não há chave |
|---|---|---|
| `cm_gated` | o código CM, se `nodot ∈ cat` ou `nodot ∈ subcat` ou `nodot[:3] ∈ cat` (portão V1) | o registro é descartado pelo portão |
| `cm_ungated` | o código CM, sempre | – |
| `who_exact_fb` | `nodot` se `nodot ∈ subcat` ou `nodot ∈ cat`; senão `nodot[:3]` se `nodot[:3] ∈ cat` | `unmapped` (V2 `NO_MAP`) |
| `who_exact` | `nodot` se `nodot ∈ subcat` ou `nodot ∈ cat` | `unmapped` |
| `who_cat3` | `nodot[:3]` se `nodot[:3] ∈ cat` | `unmapped` |

- Um registro `unmapped` é mantido e contado, mas não é chave nem ausência.
- Nenhuma projeção tenta um prefixo de 4 caracteres: `E11.65` vai para `E11`, não para `E116` (V1 e V2).

### 1.3 Espaço de comparação por contraste (R02)

- Cada contraste declara seu espaço. O padrão é **OMS** (`docs/decisoes.md`).
- Saídas CM (`cm_gated`, `cm_ungated`) são levadas ao espaço OMS pela projeção `who_exact_fb`, aplicada a cada
  registro aprovado. Registros sem projeção viram `unmapped`.
- O espaço **CM** só é permitido quando x0 e x1 (e todo híbrido) usam níveis `cm_*`. Os contrastes do bundle
  `EXTEND` usam o espaço CM: no espaço OMS, `EXTEND` não tem efeito por construção.
- No espaço OMS, `cm_gated` × `who_exact_fb` é um fator sem efeito para a presença. O portão V1 aprova exatamente os
  códigos que têm projeção, porque todo `subcat[:3]` está em `cat`.

**EX-01.** Hierarquia de brinquedo: `cat = {C61, E11, J45, R50}` e `subcat = {E119, J450, R509}`.

| código | `cm_gated` | `cm_ungated` | `who_exact_fb` | `who_exact` | `who_cat3` |
|---|---|---|---|---|---|
| `E11.9` | `E11.9` | `E11.9` | `E119` | `E119` | `E11` |
| `E11.65` | `E11.65` | `E11.65` | `E11` | unmapped | `E11` |
| `C61` | `C61` | `C61` | `C61` | `C61` | `C61` |
| `D49.2` | descartado | `D49.2` | unmapped | unmapped | unmapped |

A chave de `C61` do medicamento 4 é `AssocKey(4, "ICD-10-CM", "acm:3.0.0.20231001", "C61")` no espaço CM e
`AssocKey(4, "ICD-10-WHO", "hier:toy", "C61")` no espaço OMS.

### 1.4 Presença (R03)

- `Presence.PRESENT`: algum registro aprovado da execução tem essa chave.
- `Presence.ABSENT`: a resposta do medicamento existe e nenhum registro aprovado tem essa chave.
- `Presence.UNAVAILABLE`: a resposta do medicamento não existe, falhou ou está incompleta nessa execução. Vale para
  todas as chaves do medicamento.

Uma consulta `(contraste, a)` é **elegível** só se a presença de `a` é `PRESENT` ou `ABSENT` em x0 e em x1. As
inelegíveis entram no fluxo de elegibilidade, com o motivo, e nunca viram "aparecimento" nem "desaparecimento".

**EX-02.** O medicamento 7 não tem resposta em x0. Em x1, sua resposta produz `E119`. Em x0, a presença de
`(7, E119)` é `UNAVAILABLE`; em x1, `PRESENT`. A consulta é inelegível, não é um "aparecimento".

## 2. Três níveis de igualdade (§5.2)

1. **Bruto:** igualdade de bytes da string armazenada (UTF-8), com SHA-256 registrado.
2. **Conteúdo de extração:**
   - `json.loads` da resposta;
   - remoção **somente** da chave de topo `ResponseMetadata` (RequestId, cabeçalhos HTTP e `RetryAttempts` vão
     juntos);
   - serialização canônica `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, que ordena
     só as chaves dos objetos e nunca reordena arrays;
   - comparação exata dos floats, como `float` do Python.
   Uma chave `ResponseMetadata` aninhada (dentro de uma entidade) **não** é removida.
3. **Decisão:** igualdade do mapa `AssocKey → Presence` no espaço do contraste, mais os atributos definidos para o
   desfecho secundário (score, classe, granularidade).

A forma canônica serve só para comparar. O pipeline sempre recebe a resposta original, na ordem original.

**EX-03.** Com a resposta base `a`:

| par | bruto | conteúdo |
|---|---|---|
| `a` × `b`: só RequestId e data HTTP diferem | ≠ | = |
| `a` × `c`: `ModelVersion` diferente | ≠ | ≠ |
| `a` × `d`: duas entidades trocadas de posição | ≠ | ≠ |
| `a` × `e`: mesma resposta, com outra ordem de chaves e outros espaços | ≠ | = |
| `a` × `f`: um `ResponseMetadata` aninhado difere | ≠ | ≠ |

## 3. Evidência e semântica do núcleo pós-ACM

O núcleo (lead α, `pipeline/core.py`) é uma função determinística das respostas e de uma configuração. Esta seção
fixa a semântica que o oráculo, os exemplos e o universo de identificação usam.

### 3.1 Evidência

Por medicamento, a resposta do ACM tem um array `Entities`, na ordem original. Cada entidade tem:
- `Id`;
- `Type`;
- `Score` (`es`);
- `Traits`: pares (`Name`, `Score`), com score ausente tratado como 0;
- `ICD10CMConcepts`: pares (`Code`, `Score` = `cs`), em ordem.

Entidade sem conceitos não gera candidato.

### 3.2 Etapas, em ordem

1. **Patches.** Aplicar os patches presentes no híbrido (§4.5).
2. **Candidatos.** Para cada entidade, na ordem do array, e para cada conceito, na ordem, um candidato
   `c = (pos, eid, code, rank, es, cs, traits, type)`. `rank` é a posição do conceito ordenado por `cs` decrescente,
   com empate por `code` crescente.
3. **`sel`.**
   - `all` mantém tudo.
   - `top1` mantém, por entidade, só o candidato de `rank = 1`. Com `occ = per_entity_any`, a "entidade" é o grupo de
     entidades de mesmo `Id` (R30); com os outros níveis de `occ`, é cada entidade do array.
4. **`occ` (registros).** Os candidatos são percorridos na ordem (entidade no array, depois conceito).
   - `last_upsert`: um registro por `code`. `es` e `cs` vêm do **último** candidato do código. Os traços são a união
     dos traços das entidades de todos os candidatos do código, e o score de cada nome vem do último candidato cuja
     entidade tem esse nome. O `type` vem do último candidato.
   - `first_upsert`: igual, mas com o **primeiro** candidato, para scores e para traços.
   - `per_entity_any`: um registro por `(eid, code)`, com a regra `last_upsert` dentro do mesmo `eid`. Isso funde
     entidades de `Id` repetido, como o upsert da V2 (R30). Os traços são os das entidades desse `eid`.
5. **Predicados por registro.** O registro é aprovado se passa em todos:
   - `trait` (tabela de 3.3);
   - `ent_thr`: `es ≥ t`, ou `es > t` na variante `gt` (§4.3);
   - `icd_thr`: `cs ≥ t`, ou `cs > t` na variante `gt`;
   - `map`: o portão ou a projeção de 1.2 tem de produzir chave. Um `unmapped` reprova esse predicado, mas continua
     contado como `unmapped`.
6. **Chave e presença.** Cada registro aprovado gera a sua chave no espaço do contraste (1.3), e a presença é a de 1.4.

**Traço de decisão** (materializado em L2-M, §7): para cada registro, a chave, os candidatos membros, `es`, `cs`, os
traços, `verdict ∈ {pass, fail}` e `failed ⊆ {trait, ent_thr, icd_thr, map}`, com **todos** os predicados que
reprovaram (não só o primeiro). Também os candidatos descartados por `sel`, com motivo `sel`.

### 3.3 Regras de traço

`VETO_V1 = {LOW_CONFIDENCE, NEGATION, PERTAINS_TO_FAMILY}` e `DXS = {DIAGNOSIS, SYMPTOM, SIGN}`. `hyp` é o score de
`HYPOTHETICAL` no registro, se houver.

| nível | reprova se |
|---|---|
| `v1` (variante `std`) | algum nome em `VETO_V1`; **ou** `hyp > 0,65`; **ou** nenhum nome em `DXS` e não há `hyp ≤ 0,60` (`valid_trait`) |
| `v1` (variante `alt`) | igual a `v1 std`, mas com veto em `hyp > 0,60` (o texto da documentação) |
| `v1_hyp_le_0.6` | igual a `v1 alt` (uma só variante) |
| `v1_no_required` | igual a `v1 std`, sem o requisito `valid_trait` |
| `v2` | `NEGATION` presente (qualquer score); **ou** `type ≠ DX_NAME` |
| `neg_only` | `NEGATION` presente |

Registro sem traços reprova em `v1` e em `v1_hyp_le_0.6` (por `valid_trait`) e passa em `v1_no_required`, `v2` e
`neg_only`.

**EX-04 (`sel`).** Entidade 1 (`es` 0,90, DIAGNOSIS) com conceitos `E11.9` 0,80 e `E11.65` 0,70. Entidade 2 (`es`
0,90, SYMPTOM) com `R50.9` 0,75 e `J45.0` 0,75, um empate. Preset V1 no espaço CM:
- `sel = all` → `{E11.9, E11.65, R50.9, J45.0}`;
- `sel = top1` → `{E11.9, J45.0}` (empate resolvido por código crescente).

**EX-05 (`occ`).** Cinco entidades `DX_NAME` com DIAGNOSIS 0,90, exceto onde indicado:

| entidade | `es` | traços | conceito |
|---|---|---|---|
| e1 | 0,90 | NEGATION 0,80 e DIAGNOSIS 0,90 | `C61` 0,85 |
| e2 | 0,70 | – | `C61` 0,80 |
| e3 | 0,92 | – | `E11.9` 0,81 |
| e4 | 0,95 | – | `R50.9` 0,90 |
| e5 | 0,58 | – | `R50.9` 0,90 |

Limiares 0,60, `sel = all`, `map = cm_gated`, espaço CM:

| `occ`, `trait` | presentes |
|---|---|
| `last_upsert`, `v1` | `{E11.9}` (C61 herda a NEGATION de e1; R50.9 fica com `es` 0,58 de e5) |
| `first_upsert`, `v1` | `{E11.9, R50.9}` |
| `per_entity_any`, `v1` | `{C61, E11.9, R50.9}` |
| `last_upsert`, `v2` | `{E11.9}` |
| `per_entity_any`, `v2` | `{C61, E11.9, R50.9}` |
| `per_entity_any`, `v1`, `map = who_exact_fb`, espaço OMS | `{C61, E119, R509}` |

**EX-06 (regras de traço).** Um registro com `es` = `cs` = 0,90, tipo `DX_NAME` salvo onde indicado. "P" = passa,
"R" = reprova.

| traços | `v1` | `v1` alt | `v1_hyp_le_0.6` | `v1_no_required` | `v2` | `neg_only` |
|---|---|---|---|---|---|---|
| HYPOTHETICAL 0,62, DIAGNOSIS 0,90 | P | R | R | P | P | P |
| HYPOTHETICAL 0,55 | P | P | P | P | P | P |
| HYPOTHETICAL 0,62 | R | R | R | P | P | P |
| (nenhum) | R | R | R | P | P | P |
| PERTAINS_TO_FAMILY 0,70, DIAGNOSIS 0,90 | R | R | R | R | P | P |
| NEGATION 0,30, SIGN 0,80 | R | R | R | R | R | R |
| DIAGNOSIS 0,90, tipo `SYSTEM_ORGAN_SITE` | P | P | P | P | R | P |

## 4. Catálogo de fatores

### 4.1 Fatores

| fator | estágio | níveis | V1 → V2 | semântica |
|---|---|---|---|---|
| `occ` | post | `last_upsert`, `first_upsert`, `per_entity_any` | `last_upsert` → `per_entity_any` | 3.2 passo 4 |
| `sel` | post | `all`, `top1` | `all` → `top1` | 3.2 passo 3 |
| `ent_thr` | post | 0,55, 0,60, 0,65, 0,70 (dev/cal) | 0,60 → 0,70 | `es ≥ t` |
| `icd_thr` | post | 0,30, 0,55, 0,60, 0,65 (dev/cal) | 0,60 → 0,30 | `cs ≥ t` (na V2, MAX ≥ t equivale a "algum") |
| `trait` | post | `v1`, `v1_hyp_le_0.6`, `v1_no_required`, `v2`, `neg_only` | `v1` → `v2` | 3.3 |
| `map` | post | `cm_gated`, `cm_ungated`, `who_exact`, `who_exact_fb`, `who_cat3` | `cm_gated` → `who_exact_fb` | 1.2 |
| `patch:<id>` | acm | original / editado | – | edição semissintética da resposta (4.5) |
| `dup_ind`, `mask_drug`, `wow_rewrite`, `cut10k`, `translation` | prep | por fator | – | alteram o texto enviado. Só têm híbrido quando existe resposta armazenada para o texto resultante (§5.3) |

**Presets.**
- `V1 = {occ: last_upsert, sel: all, ent_thr: 0.60, icd_thr: 0.60, trait: v1, map: cm_gated}`
- `V2 = {occ: per_entity_any, sel: top1, ent_thr: 0.70, icd_thr: 0.30, trait: v2, map: who_exact_fb}`

**Botões de atributo.** `low_conf_thr` (0,70, `fl_low_confidence`) e `icd_hi` (0,60, rótulo HIGH) nunca entram em
`D` para alvos de presença.

**Níveis de teste.** Os níveis numéricos usados no teste são sorteados no congelamento (P4) de uma lista selada que
não está neste documento, e diferem dos níveis de dev/cal. A lista exclui todo valor queimado (§0, R28).

### 4.2 Limite de fatores

Cada contraste tem no máximo **6 fatores binários** em `D` (§7.3). Um fator é binário no contraste: nível de x0
contra nível de x1. Um bundle declarado conta como um fator (4.4).

### 4.3 Variantes de implementação (espaço K)

Uma **variante** descreve como o código que implementa um nível pode de fato se comportar. Nas execuções do
benchmark, todas as variantes são `std`. As variantes alternativas só existem nas histórias do universo de
identificação (§8), como incerteza sobre o código quando ele não pode ser executado nem inspecionado por traço.

| fator, nível | `std` | `alt` |
|---|---|---|
| `ent_thr`, `icd_thr` (qualquer t) | `≥ t` | `> t` |
| `trait = v1` | veto em `hyp > 0,65` | veto em `hyp > 0,60` |
| `occ = last_upsert` | último candidato | primeiro candidato |
| `map = cm_gated` | com portão | sem portão |
| demais | única | – |

A variante é atribuída por (fator, execução): `κ0(f)` vale para a execução x0 e `κ1(f)` para x1. Num híbrido, o
fator `f` usa o par (nível, variante) da execução de onde vem o seu nível.

**Hipóteses de divergência de nível** (usadas em §8 quando a vista não tem o vínculo ao código executado): o nível
executado pode ser o declarado ou o seu par, `v1_hyp_le_0.6 ↔ v1`, `last_upsert ↔ first_upsert` ou
`cm_gated ↔ cm_ungated`. No máximo 3 fatores com variante `alt` ou nível divergente por história.

### 4.4 Bundles (R21)

- **Bundle declarado:** um fator binário único, cujo nível x0 é um preset e cujo nível x1 é outro. Serve para
  respeitar o limite de 6 fatores ou para descrever uma mudança como unidade.
  - `V1_TO_V2`: V1 → V2.
  - `EXTEND`: `map` de `cm_gated` → `cm_ungated`, espaço CM.
- **Granularidade:** a mesma mudança em granularidades diferentes dá famílias diferentes. Cada uma é a referência
  correta na sua granularidade. A granularidade é parte do contraste e fica visível ao método (é configuração
  declarada).

**EX-14.** Entidades e1 e e2 de EX-05 (só C61), x0 = V1, x1 = V2, espaço OMS, consulta C61:
- como bundle, `D = {V1_TO_V2}` e a família é `{{V1_TO_V2}}`;
- como componentes, `D = {occ, sel, ent_thr, icd_thr, trait, map}` e a família é `{{occ}}`. Com `last_upsert`, o
  registro de C61 herda a NEGATION de e1, e as duas regras de traço vetam NEGATION. Com `per_entity_any`, e2 passa em
  qualquer combinação dos outros fatores.

### 4.5 Patches semissintéticos (R25)

- `patch:<id>` é um fator de estágio `acm`: representa uma resposta do ACM diferente, não uma configuração. Não
  aparece na configuração declarada.
- **Operações:**
  - `set_entity_score(entity, value)`
  - `set_concept_score(entity, code, value)`
  - `add_trait(entity, name, score)`
  - `remove_trait(entity, name)`
  - `swap_entities(a, b)` (troca as posições no array)
- **Invariantes de uma resposta real editada.** Os validadores rejeitam a edição que viola qualquer uma:
  - o número de conceitos por entidade não muda (0 ou 5);
  - os conceitos seguem em ordem decrescente de score, sem empate no topo;
  - os scores ficam em [0, 1];
  - os `Id` continuam únicos, salvo duplicata já existente;
  - os patches de um mesmo contraste editam alvos disjuntos (entidade, campo), então a ordem de aplicação é
    irrelevante.
- **Sinalização.** Toda edição é intervenção semissintética. `origin = semisynthetic` e o conteúdo da edição ficam
  **só** no pacote de verdade. O método vê a resposta editada como resposta de x1 e, no `Env`, cada patch aparece como
  um identificador opaco `ev:<hmac8>` (§10).

### 4.6 Certificados de irrelevância (dummy) e fatos de monotonicidade

- **Definição.** Um certificado `dummy(f, a)` afirma: para todo `S ⊆ D ∖ {f}`, `state_{S ∪ {f}}(a) = state_S(a)`. O
  avaliador confere contra a tabela-verdade. Um certificado falso torna a resposta **errada** (§9.3).
- **Regras de referência** (`semantics.dummy`). São corretas, mas incompletas: devolvem `None` quando não decidem.
  Candidatos "de `a`" são os que projetam para a chave de `a` em algum nível de `map` do contraste.
  1. `ent_thr` com níveis t0 e t1 (variante `std`): irrelevante se nenhum candidato de `a` tem `es` em
     `[min, max)`. Com `icd_thr`, o mesmo para `cs`.
  2. `sel`: irrelevante se todo candidato de `a` tem `rank = 1`.
  3. `occ`: irrelevante se cada código de `a` tem um único candidato (e um único `eid`).
  4. `map` entre `cm_gated` e `who_exact_fb` no espaço OMS: sempre irrelevante (1.3).
- **Monotonicidade.** A única propriedade assumida: baixar um limiar só pode fazer uma associação passar de ausente
  para presente, com os outros fatores fixos. Nada mais é monótono. A suficiência `S ↦ state_S(a)` é medida como não
  monótona.

**EX-15.** No contraste por componentes de EX-14, as regras certificam `sel`, `map`, `ent_thr` (nenhum `es` em
[0,60; 0,70)) e `icd_thr` (nenhum `cs` em [0,30; 0,60)). `trait` também é irrelevante na tabela-verdade, mas nenhuma
regra o certifica: o resultado é `None`. `occ` não é certificado.

## 5. Contrastes e híbridos

### 5.1 Contraste

Um contraste é:
- o grupo documental `g`;
- as configurações **executadas** `x0` e `x1`, e as **declaradas** `d0` e `d1`;
- as evidências `E0` (respostas usadas em x0) e `E1` (em x1);
- o espaço de comparação;
- `D`: o conjunto de fatores cujo par (nível, variante) executado difere entre x0 e x1, mais os patches e os fatores
  de preparação ativos. `|D| ≤ 6`.

### 5.2 Híbrido

`h_S` executa o núcleo sobre `E0` com:
- os fatores de `S` no nível e na variante de x1, e os demais no de x0;
- os patches de `S` aplicados;
- para fatores de preparação em `S`, a resposta armazenada do texto correspondente (5.3).

O `state_S(a)` é lido no espaço do contraste. `h_∅` é x0 e `h_D` é x1.

### 5.3 Admissibilidade

- `S` é admissível se o híbrido pode ser executado. Fatores `post` e `patch` são sempre admissíveis.
- Para os fatores de preparação, `S` é admissível só se existe resposta armazenada (ou chamada autorizada, ou
  simulador declarado) para o texto produzido pela combinação de preparação de `S`.
- Com as respostas de x0 e x1 disponíveis, `S` é admissível se seus fatores de preparação são nenhum ou todos os de
  `D`.

### 5.4 Declarado × executado (R05)

- A verdade usa sempre as configurações **executadas**.
- O broker do `Env` (§10) executa híbridos com os níveis executados **somente** se a vista tem o vínculo ao código
  executado. Sem ele, usa os níveis declarados de d0 e d1, com as variantes reais dos níveis usados.
- Validar o replay (`evaluate(∅) == final(x0)` e `evaluate(D) == final(x1)`) é tarefa do método. Um replay pode
  validar nas pontas e ainda assim diferir da verdade nos híbridos intermediários (EX-11).
- Se, no núcleo, o próprio `h_D` com os níveis executados não reproduz o x1 registrado, o contraste é **inválido**:
  sai do benchmark e fica registrado com o motivo. No núcleo determinístico isso não deve ocorrer; se ocorrer, é
  defeito a investigar.

## 6. Famílias mínimas e oráculo (§7.2–7.3)

### 6.1 Definições (R01, R06, R07)

- **Alteração.** `a` mudou se `state_∅(a) ≠ state_D(a)`. Se não mudou, não há família: a referência é
  `ausencia_de_mudanca`.
- **Suficiência.** `suff(S) := admissível(S) ∧ state_S(a) = state_D(a)`.
- **Conjunto mínimo.** `S` é suficiente e nenhum subconjunto próprio admissível de `S` é suficiente.
- **Família `F*`.** O conjunto de todos os conjuntos mínimos. É uma anticadeia. Uma família com dois conjuntos (como
  `{{limiar},{candidato}}`) é **uma** explicação verificada com duas vias alternativas de suficiência. Ela não é o
  estado `alternativas` (R01).
- **Completude.** A família é completa se todo `S ⊆ D` inadmissível contém propriamente algum `T` admissível e
  suficiente. Assim nenhum valor desconhecido pode alterar a minimalidade. Família incompleta → a referência do caso
  é `contrafactual_indisponivel`, e `F*_adm` (a família relativa aos admissíveis) fica registrada para pontuação
  (§9.3).
- **Não monotonicidade.** `nonmonotone = ∃ S suficiente, ∃ T ⊋ S admissível e não suficiente.` É só um rótulo
  descritivo e não muda a família.

### 6.2 Algoritmo do oráculo

Enumera todos os `2^|D|` subconjuntos, executa `h_S` para os admissíveis (um run por `S`, que serve a todas as
associações do grupo) e, por associação:

```
sub[S]     = suff[S] ∨ ⋁_{i∈S} sub[S∖{i}]
minimal[S] = suff[S] ∧ ¬⋁_{i∈S} sub[S∖{i}]
```

- Custo `O(|D| · 2^|D|)`. Com `sub` definido sobre admissíveis, conjuntos intermediários inadmissíveis são tratados
  corretamente.
- Os testes de propriedade comparam com uma referência ingênua `O(3^n)`. Verificam que o resultado é uma anticadeia,
  que todo membro é suficiente, que nenhum subconjunto próprio admissível de um membro é suficiente, e que todo
  suficiente contém um membro.
- O oráculo é independente da busca dos métodos.

**EX-07 (exemplo de §7.2).**
- Entidade e1: `es` 0,59, `cs` 0,90, DIAGNOSIS, código C61.
- x0 = V1; x1 = V1 com `ent_thr` 0,58 e `icd_thr` 0,55.
- `patch:p1` faz `set_entity_score(e1, 0.62)`.
- `D = {ent_thr, patch:p1, icd_thr}`.

Resultado: a associação muda (ausente → presente); suficientes = todo `S` que contém `ent_thr` ou `patch:p1`;
`F* = {{ent_thr},{patch:p1}}`; `icd_thr` não integra nenhum conjunto; `nonmonotone = falso`; família completa.

**EX-08 (cancelamento).**
- e1: `es` 0,65, `cs` 0,90, DIAGNOSIS.
- x0 `ent_thr` 0,60 → x1 0,70; `patch:p2` põe `es` = 0,75. `D = {ent_thr, patch:p2}`.
- `state`: ∅ presente, `{ent_thr}` ausente, `{patch:p2}` presente, `D` presente.

Os dois fatores têm efeito isolado, mas a associação **não mudou**. A referência é `ausencia_de_mudanca`.

**EX-09 (interação).**
- e1: `es` 0,58, `cs` 0,58.
- `ent_thr` 0,60 → 0,55 e `icd_thr` 0,60 → 0,55.

Só `D` é suficiente: `F* = {{ent_thr, icd_thr}}`.

**EX-10 (não monótono).**
- e1: `es` 0,58, `cs` 0,62.
- `ent_thr` 0,60 → 0,55; `icd_thr` 0,60 → 0,65; `patch:p3` põe `cs` = 0,66.

Suficientes: `{ent_thr}`, `{ent_thr, patch:p3}` e `D`. `F* = {{ent_thr}}` e `nonmonotone = verdadeiro`:
`{ent_thr, icd_thr}` não é suficiente.

**EX-13 (inadmissível, família incompleta).**
- Fatores de preparação `dup_ind` e `mask_drug`, e `ent_thr` 0,60 → 0,55.
- Há resposta armazenada só para o texto de x0 (e1 com `es` 0,58) e para o de x1 (e1 com `es` 0,62). Então
  `{dup_ind}` e `{mask_drug}` são inadmissíveis.
- Resultado: `F*_adm = {{ent_thr},{dup_ind, mask_drug}}`. A família é **incompleta**, porque `{dup_ind}` não contém
  nenhum admissível suficiente. A referência é `contrafactual_indisponivel`.

### 6.3 Busca correta do lado do método (referência BFS)

Esta é a busca de referência usada para definir a "necessidade de orçamento" (§9.3) e como base de M.

1. Avaliar `∅` e `D` (validação de replay), nessa ordem.
2. Para `k = 1 … |D|−1`, em ordem crescente, e dentro do nível em ordem lexicográfica da tupla ordenada de nomes
   canônicos:
   - pular `S` se contém um suficiente já achado;
   - pular `S` se contém um fator com certificado dummy válido;
   - pular `S` se é inadmissível (fica "desconhecido");
   - senão, avaliar. Se é suficiente, registrar.
3. `D` é mínimo se nenhum suficiente achado está contido nele.

- Todo `S` avaliado teve os seus subconjuntos próprios avaliados ou podados, então todo suficiente achado é mínimo
  mesmo sem monotonicidade.
- Se o orçamento acaba no meio, o resultado é uma família parcial verificada, marcada incompleta.
- Com várias consultas num contraste, a busca é conjunta: `S` só é pulado se é podado para **todas** as consultas
  ainda abertas.

**EX-16.** `D = {A, B, C}`, suficientes `{A}`, `{A,C}`, `{B,C}` e `{A,B,C}`.
- Orçamento ilimitado: avalia ∅, D, A, B, C e BC, em 6 avaliações. `F = {{A},{B,C}}`, completa.
- Orçamento 5: para antes de BC, com `{{A}}` parcial e incompleta.

## 7. Perfis de evidência, capacidades e orçamento

### 7.1 Artefatos por perfil (R04, R19, R23)

"●" = visível; "–" = ausente.

| artefato (tipo) | L1 | L2-R | L2-M | N1 | N2 |
|---|---|---|---|---|---|
| `source_pt`: texto PT da fonte | ● | ● | ● | ● | ● |
| `final`: saída final por execução | ● | ● | ● | ● (esquema md V1) | ● (esquema md V2) |
| `hashes`: SHA-256 de todo artefato da execução (texto enviado, tradução, resposta, saída) | ● | ● | ● | – | – |
| `config_declared`: prompts, parâmetros, commit declarado, limiares, mapeamento | ● | ● | ● | ● (constantes de 405a10c) | ● (parâmetros de HEAD) |
| `translation_en` | – | ● | ● | ● | ● |
| `submitted_text` | – | ● | ● | – | ● |
| `acm_response`: resposta completa | – | ● | ● | ● | ● |
| `code_link`: vínculo ao código executado, com os níveis executados | – | ● | ● | – | – |
| `env_versions`: terminologia (`hier:<sha>`), bibliotecas | – | ● | ● | – | – |
| `ops_actions`: ações operacionais | – | ● | ● | – | – |
| `trace`: registros com decisões (3.2), por execução | – | – | ● | parcial: `entity`/`trait` V1 (por `(med, code)`, última ocorrência, união de traços) | parcial: `entity_icd`, `entity_trait`, `cutoff_audit` |

- **L3-R / L3-M** = L2-R / L2-M mais as **realizações de referência** (R23), visíveis só em L3.
  - Piloto: 6 referências e 4 de avaliação por texto e perfil. Teste: 3 e 2.
  - O par-alvo usa realizações de avaliação e é o mesmo em L2 e L3.
  - No núcleo determinístico as referências repetem x0, então L3 ≡ L2 (equivalente, não rodado em separado).
- **N1 / N2** (R19) emulam as políticas de preservação V1 e V2 sobre as mesmas execuções, no esquema histórico. Não
  têm vínculo ao código executado. O replay só é permitido para `S` expressável no código histórico:
  - N1: `ent_thr`, `icd_thr`, `trait` ∈ {`v1`, `v1_hyp_le_0.6`, `v1_no_required`}, portão de `map`;
  - N2: `ent_thr`, `icd_thr`.

### 7.2 Ablações e perdas combinadas

| id | remove de L2-R/L2-M | efeito no replay (R29) |
|---|---|---|
| A1 | `submitted_text` | nenhum para fatores pós-ACM. Sem texto, híbridos com fatores de preparação ficam inadmissíveis |
| A2 | `acm_response` completa, mantendo só o conceito top-1 por entidade | o broker replica sobre a evidência top-1 e o replay pode não validar |
| A3 | `code_link` | o broker replica com os níveis **declarados** (5.4) |
| A4 | `env_versions` | nenhum (o broker usa o ambiente real). O método não sabe a versão da terminologia |
| A5 | `ops_actions` | nenhum para presença |
| A6 | registros reprovados do `trace` (só em L2-M; mantém os aprovados) | nenhum |

Perdas combinadas (propostas; congeladas antes do teste):
- `C1 = A1 + A3`
- `C2 = A2 + A6`
- `C3 = A3 + A4 + A5`
- `C4 = A1 + A2 + A3`

Um teste confere, artefato a artefato e byte a byte, que `L1 ⊂ L2-R ⊂ L2-M` e que cada ablação remove exatamente um
item (**EX-22**).

### 7.3 Capacidades (§6.4) e células

- **R-A:** o broker executa qualquer `S` admissível.
- **R-B:** o serviço externo está indisponível. O broker só executa `S` sem fatores `prep`, nem `acm` que não sejam
  patch.
- **R-C:** o broker não executa nada. `evaluate` levanta `Unavailable`.

As células (R22):
- **n/a estrutural** (não rodadas, não contam como falha): L1 × R-A e L1 × R-B, porque L1 não guarda respostas.
  Nessas células L1 só existe com R-C.
- **Equivalentes** (rodadas uma vez e reportadas como iguais): R-B ≡ R-A quando `D` não tem fator `prep` nem `acm`
  além de patches. É o caso de todo o núcleo local, exceto EX-13 e a família P. Também L3 ≡ L2 no núcleo
  determinístico.
- A2 × R-A é rodada: o replay degradado é justamente o objeto da ablação.

### 7.4 Orçamento (R08, R09)

- **Unidade:** uma avaliação é um run híbrido do grupo documental inteiro para um `S` distinto.
  - `evaluate(∅)` e `evaluate(D)` contam.
  - Repetir `S` não custa (cache por contraste).
  - Handles de fatores cujo nível, tal como o broker o usa, é igual em x0 e x1 são retirados antes da chave do cache.
  - Pedir `S` inadmissível ou pedir em R-C levanta `Unavailable` e custa 0.
  - Ler os finais observados não conta.
- **Por contraste**, compartilhado por todas as consultas: `b ∈ {16, 32, 64}`. Com `|D| ≤ 6`, `b = 64` permite a
  enumeração completa ("regime suficiente").
- **H1a primário** usa `b = 64`; as curvas de 16 e 32 são secundárias **[revisar]**.
- Custos em bytes lidos, CPU e memória são medidos à parte (§10).

## 8. Referência de identificação (§7.4, R10)

### 8.1 História e observação

- Uma **história** `h` para a consulta `a` tem:
  - a evidência dos candidatos de `a`;
  - os níveis executados de x0 e x1;
  - as variantes `κ0` e `κ1` (4.3).

  As configurações declaradas e todo o resto do grupo são fixos. Cada história determina, pelo núcleo, a
  tabela-verdade de `a` e daí a família `F(h)` (§6), ou "sem mudança".
- A **observação** `o_{v,r}(h)` é a tupla dos componentes abaixo, cada um função determinística de `h`:

| componente | presente quando | conteúdo |
|---|---|---|
| declarado | sempre | d0 e d1 (constantes no universo) |
| finais | sempre | `state` de `a` em x0 e em x1 |
| hashes | L1, L2-* | igualdade dos hashes de resposta entre x0 e x1 |
| evidência | L2-*, N* | candidatos de `a` (só top-1 em A2) |
| níveis executados | vínculo ao código visível | níveis executados de x0 e x1 (não as variantes) |
| traço | L2-M (aprovados só, em A6) | por registro de `a`, em x0 e x1: `verdict` e o conjunto `failed` |
| replay | R-A (ou R-B, restrito) | `state_S(a)` retornado pelo broker para todo `S ⊆ D_vis`. `D_vis` é o diff executado com vínculo e o declarado sem ele; o broker usa os níveis da regra 5.4 e as variantes da história |

- `W(v, r) = { F(h′) : h′ ∈ U, o_{v,r}(h′) = o_{v,r}(h*) }`, onde `h*` é a história verdadeira. `F(h*) = F*` está em
  `W` por construção.

### 8.2 Universo declarado U (β3 implementa)

- **Símbolos de candidato:** (faixa de `es`, faixa de `cs`, `top1`, classe de traço, classe de tipo, classe de `map`).
  - As faixas de score são cortadas nos níveis de x0 e x1 dos fatores de limiar em `D`, com um ponto "exatamente no
    limiar" por causa da variante `gt`.
  - A classe de traço é (NEG, LOW_CONFIDENCE, PERTAINS_TO_FAMILY, faixa de HYP ∈ {nenhum, ≤ 0,60, (0,60; 0,65],
    > 0,65}, presença de DXS).
  - A classe de tipo é DX_NAME ou outro. A classe de `map` é subcategoria exata, fallback de categoria ou `unmapped`.
  - Símbolos com a mesma assinatura de comportamento (o mesmo vetor aprovado/reprovado sobre todos os híbridos e
    variantes) são fundidos.
- **Bundle de candidatos:** sequência ordenada de até `L = 4` símbolos, com a partição em entidades. A ordem importa
  por `occ`.
- **Níveis e variantes:** as hipóteses de 4.3, com no máximo 3 fatores alterados.
- **Expansão** em largura por comprimento, deduplicando por classe `(tabela-verdade, observação)`. `saturated` =
  passar de `L−1` para `L` não criou classe nova.

### 8.3 Limites e estado de identificação

- **`W_hi`:** famílias das classes de U com a mesma observação **marginal** em `a`. As demais associações ficam livres.
- **`W_lo` ⊆ `W_hi`:** famílias das classes cuja testemunha **se eleva** ao grupo verdadeiro.
  1. Substituir os candidatos de `a` na evidência real pelo bundle da testemunha, preservando as invariantes de 4.5.
  2. Reexecutar.
  3. Exigir que toda observação visível do grupo (finais das outras chaves, traços, replay) fique inalterada.

  `F*` está sempre em `W_lo`.
- **Estado:**
  - `identificado`: `W_lo = W_hi = {F*}` e U saturado.
  - `ambiguo`: `|W_lo| ≥ 2`. Existem duas testemunhas, então a ambiguidade está demonstrada mesmo sem saturação.
  - `indeterminado`: `|W_lo| = 1` e (`|W_hi| > 1` ou U não saturado). É reportado e excluído dos denominadores
    primários.
- **Escopo:** a identificação é relativa a U. Ausência de testemunha não é identificação global.
- **Adequação** (só dev/cal):
  - toda tabela-verdade de associação alterada de dev/cal tem de ser gerada por U;
  - as famílias realizadas no corpus dev/cal com a mesma observação têm de estar em `W_lo`.

  Os grupos de teste nunca entram nessa checagem.

### 8.4 Quando U é necessário

U **não** é necessário, e `W = {F*}`, quando valem todas:
- a vista tem a resposta completa (sem A2, e sem A1 se `D` tem fator de preparação);
- a vista tem o vínculo ao código (não é L1, A3, N1 nem N2);
- a capacidade executa todo `S` admissível (R-A, ou R-B sem fatores `prep`/`acm`).

Isso cobre L2-R e L2-M em R-A nas famílias N, F, M, O e X. Nos demais casos (L1, R-C, N1/N2 e as ablações da família
I), `W` é computado sobre U.

**EX-11 (divergência documentação/código de HYPOTHETICAL).**
- e1: `es` 0,58, `cs` 0,90, HYPOTHETICAL 0,62, DIAGNOSIS 0,90, C61.
- Declarado: d0 = V1 com `trait = v1_hyp_le_0.6` (a documentação); d1 = V1 com `ent_thr` 0,55.
- Executado: x0 = V1 (`trait = v1`, o código), x1 = d1. Variantes `std`.
- `D` executado = `{ent_thr}`. `F* = {{ent_thr}}`.
- U: `es` ∈ {0,58; 0,62} × HYP ∈ {nenhum, 0,62, 0,70} × `trait` executado em x0 ∈ {`v1_hyp_le_0.6`, `v1`} ×
  `κ(trait)` em x0 e x1 ∈ {`std`, `alt`}.

| vista × capacidade | `W` |
|---|---|
| L1 × R-C | `{{ent_thr}}`, `{{ent_thr, trait}}`, `{{trait}}` (3) |
| L2-R−A3 × R-A (replay com o declarado; valida nas pontas) | `{{ent_thr}}`, `{{ent_thr, trait}}` (2) |
| L2-R−A3 × R-C | 2, as mesmas |
| L2-R × R-C | 2, as mesmas (a variante de x0 não é observável) |
| L2-M × R-C | `{{ent_thr}}` (1): o traço de x0 mostra `failed = {ent_thr}`, sem `trait` |
| L2-R × R-A | `{{ent_thr}}` (1) |

Um método que confia no replay validado em L2-R−A3 × R-A conclui `{{ent_thr, trait}}` e erra. A saída correta
nessa vista é `alternativas` com as duas famílias.

**EX-12 (par testemunha de §7.4).**
- e1 com DIAGNOSIS; `ent_thr` e `icd_thr`, ambos 0,60 → 0,55; declarado = executado.
- U: `(es, cs)` ∈ {0,58; 0,90}².
- A verdade é `(0,58; 0,90)`, com `F* = {{ent_thr}}`. A testemunha `(0,90; 0,58)` tem `{{icd_thr}}` e a mesma
  observação L1.
- `W(L1 × R-C) = {{{ent_thr}}, {{icd_thr}}, {{ent_thr, icd_thr}}}`; `W(L2-R × R-C) = W(L2-R × R-A) = {{{ent_thr}}}`.

## 9. Saídas, lastro e pontuação

### 9.1 Taxonomia (§7.4; `types.OutputState`)

- **Categóricas:**
  - `explicacao_verificada`: exatamente **uma** família;
  - `alternativas`: duas ou mais famílias distintas;
  - `ausencia_de_mudanca`;
  - `compativel_com_variabilidade`.
- **Abstenções:** `informacao_insuficiente`, `orcamento_esgotado`, `contrafactual_indisponivel`.
- **À parte:** `falha_de_execucao`. Sua taxa é reportada, e nunca é lida como ausência.

**Validação do esquema (EX-23).** Saída inválida é convertida em `falha_de_execucao` com motivo `invalid_output`:
- `explicacao_verificada` sem exatamente uma família;
- `alternativas` com menos de duas famílias distintas;
- família vazia, com conjunto vazio, ou que não é anticadeia;
- estado não categórico com famílias.

### 9.2 Lastro de `explicacao_verificada` (R12)

A saída traz certificados `(kind, S ou f, valor)`:

| `kind` | afirma | disponível quando |
|---|---|---|
| `final` | `∅` insuficiente e `D` suficiente | sempre (finais observados) |
| `eval` | `suff(S)` = valor, com `S` avaliado neste contraste (consta do log do `Env`) | R-A/R-B |
| `trace` | `suff(S)` = valor, derivado dos traços armazenados | L2-M |
| `dummy` | `f` irrelevante para `a` (4.6) | qualquer |

O avaliador:
1. Traduz handles para nomes canônicos e intersecta cada `S` com `D` executado.
2. Confere **cada** afirmação contra a tabela-verdade: o valor real, não o que o broker devolveu. Uma afirmação falsa
   → `errado`.
3. Confere a **cobertura**: todo `S ⊆ D` tem de ter valor certificado, ou conter propriamente um `S` certificado
   suficiente, ou conter um fator certificado dummy.
4. Sem cobertura, a saída não tem lastro → `indevidamente_exclusivo`.

**EX-21.** Tabela-verdade de EX-10, afirmação `{{ent_thr}}`.
- (a) `final` para ∅ e D, e `eval` para `{ent_thr}` (suf.), `{icd_thr}`, `{patch:p3}` e `{icd_thr, patch:p3}`
  (insuf.): coberto e verdadeiro → lastro.
- (b) Sem `{icd_thr, patch:p3}`: sem cobertura.
- (c) Com `eval {ent_thr, icd_thr}` suficiente: afirmação falsa.
- (d) `dummy(icd_thr)` no lugar das avaliações com `icd_thr`: cobre, mas o certificado é falso (`{ent_thr}` é
  suficiente e `{ent_thr, icd_thr}` não) → errado.

### 9.3 Tabela de pontuação (R11, R26)

A **célula de verdade** de uma consulta elegível é uma das seguintes:
- `identificado`, `ambiguo` ou `indeterminado` (8.3), se ela mudou e a família é completa;
- `incompleta`, se ela mudou e a família é incompleta;
- `inalterado`, se ela não mudou.

Na célula `variabilidade` (só simulador ou campanha), `compativel_com_variabilidade` é correta, `ausencia_de_mudanca`
é errada e uma explicação é errada. Pares de intervenção sob ruído não são pontuados por consulta: seguem §9.4 do
protocolo (efeitos médios).

**Resultados:**
- `correto_sustentado`, `errado`, `indevidamente_exclusivo` e `nao_comprometido` (categórico sem erro e sem acerto);
- `abstencao_apropriada`, `abstencao_desnecessaria`;
- `falha`;
- `excluido` (célula `indeterminado`).

**Precedência:** errado > indevidamente exclusivo > não comprometido > correto sustentado.

**Explicação verificada V(F):**

| célula | regra |
|---|---|
| `identificado` | certificado falso → errado; `F ≠ F*` → errado; `F = F*` sem lastro → indevidamente exclusivo; `F = F*` com lastro → correto sustentado |
| `ambiguo` | `F = F*` → indevidamente exclusivo (acerto por acaso); senão → errado |
| `incompleta` | `F = F*_adm` → indevidamente exclusivo; senão → errado |
| `inalterado` | errado (falsa atribuição) |
| `indeterminado` | excluído |

**Alternativas A(𝒜):**

| célula | regra |
|---|---|
| `identificado` | `F* ∉ 𝒜` → errado; senão → não comprometido |
| `ambiguo` | `F* ∉ 𝒜` → errado; `W_lo ⊄ 𝒜` → indevidamente exclusivo; `𝒜 ⊆ W_hi` → correto sustentado; senão (sobra além de `W_hi`) → não comprometido |
| `incompleta` | `F*_adm ∉ 𝒜` → errado; senão → não comprometido |
| `inalterado` | errado (falsa atribuição) |
| `indeterminado` | excluído |

**Demais estados:**

| estado | `identificado` / `ambiguo` / `incompleta` | `inalterado` | `indeterminado` |
|---|---|---|---|
| `ausencia_de_mudanca` | errado | correto sustentado | excluído |
| `compativel_com_variabilidade` (núcleo determinístico) | errado | não comprometido | excluído |
| `informacao_insuficiente` | apropriada em `ambiguo` e `incompleta`; desnecessária em `identificado` | desnecessária | excluído |
| `contrafactual_indisponivel` | apropriada em `incompleta`; desnecessária senão | desnecessária | excluído |
| `orcamento_esgotado` | apropriada se a necessidade do contraste passa de `b`; desnecessária senão | desnecessária | excluído |
| `falha_de_execucao` | falha | falha | falha (fora dos primários) |

A **necessidade** de um contraste é o número de avaliações da BFS conjunta de referência (6.3). Ela usa os
certificados dummy de referência que a vista permite: trace em L2-M, evidência em L2-R.

Exemplos de célula × estado:

| id | célula | saída | resultado |
|---|---|---|---|
| EX-S01 | identificado, `F* = F1` | V(F1), com lastro | correto sustentado |
| EX-S02 | identificado | V(F1), sem lastro | indevidamente exclusivo |
| EX-S03 | identificado | V(F2) | errado |
| EX-S04 | identificado | A({F1, F2}) | não comprometido |
| EX-S05 | identificado | A({F2, F3}) | errado |
| EX-S06 | identificado | ausência de mudança | errado |
| EX-S07 | identificado | compatível com variabilidade | errado |
| EX-S08 | identificado | informação insuficiente | abstenção desnecessária |
| EX-S09 | identificado, necessidade 6, `b` = 4 | orçamento esgotado | abstenção apropriada |
| EX-S10 | identificado, necessidade 6, `b` = 64 | orçamento esgotado | abstenção desnecessária |
| EX-S11 | identificado | contrafactual indisponível | abstenção desnecessária |
| EX-S12 | ambíguo, `W_lo = W_hi = {F1, F2}` | V(F1) | indevidamente exclusivo |
| EX-S13 | idem | V(F2) | errado |
| EX-S14 | idem | A({F1, F2}) | correto sustentado |
| EX-S15 | idem | A({F1, F3}) | indevidamente exclusivo |
| EX-S16 | idem | A({F1, F2, F3}) | não comprometido |
| EX-S17 | idem | A({F2, F3}) | errado |
| EX-S18 | ambíguo, `W_lo = {F1, F2}`, `W_hi = {F1, F2, F3}` | A({F1, F2, F3}) | correto sustentado |
| EX-S19 | ambíguo | informação insuficiente | abstenção apropriada |
| EX-S20 | ambíguo | ausência de mudança | errado |
| EX-S21 | indeterminado, `W_lo = {F1}`, `W_hi = {F1, F2}` | V(F1) | excluído |
| EX-S22 | incompleta, `F*_adm = F4` | contrafactual indisponível | abstenção apropriada |
| EX-S23 | incompleta | V(F4) | indevidamente exclusivo |
| EX-S24 | incompleta | V(F1) | errado |
| EX-S25 | incompleta | A({F4, F1}) | não comprometido |
| EX-S26 | inalterado | ausência de mudança | correto sustentado |
| EX-S27 | inalterado | V(F1) | errado |
| EX-S28 | inalterado | A({F1, F2}) | errado |
| EX-S29 | inalterado | compatível com variabilidade | não comprometido |
| EX-S30 | inalterado | informação insuficiente | abstenção desnecessária |
| EX-S31 | identificado | falha de execução | falha |
| EX-S32 | ambíguo | compatível com variabilidade | errado |
| EX-S33 | incompleta | informação insuficiente | abstenção apropriada |
| EX-S34 | incompleta | ausência de mudança | errado |
| EX-S35 | identificado | V(F1), com lastro e um certificado falso | errado |

Legenda:
- `F1 = {{ent_thr}}`
- `F2 = {{ent_thr, trait}}`
- `F3 = {{trait}}`
- `F4 = {{ent_thr},{dup_ind, mask_drug}}`

O teste confere que a tabela é **total**: todo par (célula, estado) tem exatamente um resultado.

## 10. Métricas (§11; R13, R14)

### 10.1 Conjuntos de consultas

| conjunto | conteúdo |
|---|---|
| `Q_c` | alteradas em `identificado` ou `ambiguo` |
| `Q_inc` | alteradas em `incompleta` |
| `Q_ind` | alteradas em `indeterminado` |
| `Q_u` | inalteradas |

As inelegíveis ficam fora, com contagem por motivo.

### 10.2 Primárias

Estimadores de razão agregados por consulta, com inferência por grupo (§12):
- `cobertura = #correto_sustentado(Q_c) / |Q_c|`. `falha` fica no denominador como não coberta.
- `cobertura_bruta = #categóricas(Q_c) / |Q_c|`.
- `risco_seletivo = (#errado + #indevidamente_exclusivo) / #categóricas`, sobre `Q_c ∪ Q_inc`.
- **Controle nulo:**
  - falsas atribuições por contraste da família N;
  - **principal**: fração de grupos com ≥ 1 falsa atribuição em contrastes N.

  Falsa atribuição = V ou A numa consulta de `Q_u`.

### 10.3 Secundárias

- Cobertura sobre `Q_u` (`ausencia_de_mudanca` correta), e a taxa de falsa atribuição sobre todo `Q_u`.
- **Média por grupo** das métricas primárias (peso igual por grupo).
- **Precisão, revocação e F1 por classe de causa.**
  - A classe é o nome canônico do fator; todo `patch:*` é a classe `evidence`.
  - Previsto = `∪F` das saídas V; verdadeiro = `∪F*`.
  - É análise auxiliar (união de causas, §11.2).
- **Conjuntos**, só com oráculo completo e saída V:
  - acerto exato da família;
  - precisão `|F ∩ F*| / |F|` e revocação `|F ∩ F*| / |F*|`, com conjuntos como elementos.
- **Outras:**
  - exclusividade indevida;
  - identificação de alternativas (acerto em `ambiguo`);
  - abstenção por estado, motivo e adequação;
  - `falha` por método;
  - `|Q_ind|` e `|Q_inc|` por perfil;
  - estabilidade da explicação entre repetições do método.
- **Custo**, bruto e amortizado:
  - avaliações distintas, bytes lidos, CPU e pico de RSS;
  - o bruto é por contraste; o amortizado divide o custo do contraste pelas suas consultas;
  - as referências de L3 e a reconstrução inicial entram (§10.2 do protocolo).
- **Armazenamento:** bytes brutos e deduplicados por perfil, por execução e documento, e por associação (§11.4).

Toda métrica é **sempre** estratificada por origem: `semisynthetic` se `D` contém `patch:*`, senão `real`. Também
por família de cenário. As probabilidades de inclusão servem só às estimativas populacionais ponderadas (§4.4).

**EX-17.** 11 consultas em 4 contrastes e 3 grupos (dados no JSON):
- `cobertura` = 1/5 = 0,2; `cobertura_bruta` = 3/5 = 0,6;
- `risco_seletivo` = 2/4 = 0,5;
- fração de grupos N com falsa atribuição = 1/2;
- falsas atribuições por contraste N = 0,5;
- cobertura em `Q_u` = 2/4;
- taxa de falha em `Q_c` = 1/5;
- `|Q_ind|` = 1.

## 11. Ambiente dos métodos (`Env`) e esquema de saída

### 11.1 Interface

```python
class Env(Protocol):
    def contrast(self) -> ContrastInfo            # opaque contrast id, run ids ("x0", "x1"), comparison space
    def artifacts(self) -> Sequence[ArtifactRef]  # opaque ref, kind (table 7.1), run
    def read(self, ref: ArtifactRef) -> bytes     # metered (bytes)
    def config(self, run: str) -> Mapping[str, str]            # declared config, public schema
    def executed_config(self, run: str) -> Mapping[str, str]   # raises Unavailable without code_link
    def final(self, run: str) -> Mapping[AssocKey, Presence]
    def factors(self) -> Sequence[str]            # evaluable handles (below)
    def capability(self) -> str                   # "R-A" | "R-B" | "R-C"
    def evaluate(self, apply: frozenset[str]) -> EvalResult
        # presence map of the whole group + trace of the hybrid; cost per 7.4;
        # raises Unavailable (R-C, inadmissible), BudgetExhausted; unknown handle -> ValueError (no cost)
    def meter(self) -> Meter                      # evaluations, bytes read, cpu seconds, peak RSS; raw and amortized
```

**`factors()`** devolve:
- os nomes de configuração do diff declarado;
- os do diff executado, se há `code_link`;
- um handle opaco `ev:<hmac8>` por patch, se as respostas estão visíveis.

Os nomes de configuração são públicos. Os handles não revelam família, rótulo, semente nem edição.

**Consulta:** `Query(qid, key: AssocKey)`. A ordem das consultas é embaralhada.

```python
class Method(Protocol):
    name: str
    def explain(self, env: Env, queries: Sequence[Query]) -> Mapping[str, Explanation]  # one budget per contrast

@dataclass(frozen=True)
class Explanation:
    qid: str
    state: OutputState
    families: tuple[tuple[tuple[str, ...], ...], ...]   # handles; validated as in 9.1
    certificates: tuple[Certificate, ...]               # 9.2
    reason: str                                          # required for abstentions
    confidence: float | None

@dataclass(frozen=True)
class Certificate:
    kind: Literal["final", "eval", "trace", "dummy"]
    subject: tuple[str, ...]      # S (handles) or (factor,)
    value: bool                   # sufficient? / dummy?
```

Motivos padronizados de abstenção:
- `output_diff_only`
- `replay_invalido`
- `evidencia_oculta`
- `ambiguidade`
- `sem_resposta_armazenada`
- `orcamento`

### 11.2 Isolamento (§6.3, §14)

- O código de método não importa `habench.pipeline`, `habench.oracle` nem `habench.scenarios`. Um *audit hook* nega
  os imports, a abertura do arquivo canário de verdade, sockets, `subprocess` e `listdir` fora da vista.
- `evaluate` só existe via RPC do broker.
- **Nomes e metadados:**
  - identificadores HMAC-SHA256, com a chave guardada só na verdade;
  - nomes de arquivo uniformes e mtimes constantes;
  - nenhum nome de família, rótulo, semente, edição ou forma em nomes de arquivo, chaves ou conteúdo, conferido
    também em conteúdo descompactado.
- A verdade fica num diretório nunca montado para métodos.
- **Comparações:** as de algoritmo usam a mesma vista; as de informação usam o mesmo algoritmo (§10).

## 12. Famílias de cenários (§8)

**Regras comuns:**
- A evidência é real, com patches opcionais (4.5).
- Por contraste, no máximo 25 consultas alteradas e 25 inalteradas, sorteadas com semente e com probabilidades de
  inclusão registradas. As inalteradas saem das chaves candidatas das duas execuções (presente/presente ou
  ausente/ausente).
- A razão entre alteradas e inalteradas é a mesma em todas as famílias.
- Os níveis dos fatores diferem entre dev, cal e teste; os de teste são selados (4.1).
- Cotas de forma e calibração só com dev/cal (D2).
- **Nada de verdade, vista ou execução é materializado para grupos de teste antes do congelamento:**
  `SealedError`.

| família | geração | contrastes/grupo |
|---|---|---|
| N | (a) Só metadados de transporte mudam: `D = ∅`, respostas iguais no nível 2. (b) Só fatores certificados dummy: `map` no espaço OMS, um limiar movido numa faixa vazia. (c) Repetição real: medicamentos do grupo com o mesmo texto enviado. (d) Estocástico: só simulador, reportado à parte. Referência: tudo `ausencia_de_mudanca`. Distinguir nulo local de nulo prospectivo. | 3 |
| F | Um fator por contraste: `ent_thr`, `icd_thr` ou `trait`, com níveis de 4.1. Patches de borda levam um score exatamente a `t` e a `t − 1e-9`. Referência típica: famílias unitárias. | ~7 |
| M | Pares de `map` com a terminologia fixa. `unmapped` é preservado. Mudança de granularidade sinalizada por relação ancestral válida. `EXTEND` no espaço CM. | ~5 |
| O | `occ` × `sel`, mais `first_upsert`. Preferir grupos com alta multiplicidade de candidatos. Um patch opcional troca posições de entidades. | ~5 |
| X | (i) O bundle real `V1_TO_V2`, nas duas granularidades; nos grupos de teste fica fora do conjunto confirmatório (D2). (ii) Amostragem com rejeição guiada pelo oráculo: k de 3 a 6 fatores, ao menos um sem efeito verificado e ao menos um par oposto, com cotas de forma (unitária, vários conjuntos, interação, não monótona) fixadas em dev/cal. (iii) O exemplo de §7.2 como caso semissintético (não selado; é público). | ~6 |
| I | As mesmas execuções de F/M/O/X cruzadas com L1, L2-R, L2-M, A1–A6, C1–C4 e R-A/R-B/R-C, com as células n/a e as equivalentes de 7.3. Execuções novas só para divergência declarado ≠ executado (regra HYPOTHETICAL, portão, `occ`) num subconjunto de F/X. | – |
| P | **Só catalogada** (R20). Preparação: duplicação da indicação, `<drug>`, "with or without", corte. Sem chamadas novas nem simulador nesta fase, toda instância tem referência `contrafactual_indisponivel` e não entra em nenhum denominador. O catálogo registra os fatores e a divergência real da V2 (E14). | – |

## 13. Plano de análise estatística (§11.3; R09, R15–R18, R27)

### 13.1 Estimandos

Todos na população de contrastes de teste da família indicada, com o mesmo método M:

| hipótese | estimando | região | teste |
|---|---|---|---|
| H1a | `Δa = cob(L2-R) − cob(L2-M)` | R-A, `b = 64`; famílias F, M, O, X | não inferioridade a −0,02 |
| H1b **[revisar]** | `Δb = cob(com evidência efetiva) − cob(sem ela)`, agregado sobre dois estratos pré-declarados da família I | divergência: L2-R × (L2-R − A3), em R-A; perda de replay: L2-M × L2-R, em R-C | superioridade (`Δb > 0`), com a guarda `risco(com) − risco(sem) ≤ +0,02` no limite superior de 95%. Se a guarda falha, H1b não é sustentada |
| H2 (R18) | composto: (i) fração de grupos nulos com falsa atribuição, L3 < L2 (superioridade); **e** (ii) `cob(L3) − cob(L2) > −0,02` (não inferioridade), na campanha pertinente | – | – |

- Sem campanha de teste (`docs/decisoes.md`), H2 não é executada confirmatoriamente: entra no Holm com p = 1. O piloto
  dev/cal é exploratório.
- Armazenamento e tempo de H1a são desfechos descritivos (§11.4).
- Os resultados por ablação de H1b são secundários, um a um.

### 13.2 Reamostragem

- Bootstrap pareado por **grupo documental**. Os grupos de teste são reamostrados com reposição, preservando todas as
  suas consultas, contrastes e repetições. Os dois braços são recomputados nos mesmos grupos reamostrados.
- `B = 2000`, `numpy.random.Generator(PCG64(20260930))`.
- IC percentil de 95%.
- Estabilidade: repetir com as sementes 20260931 e 20260932. Se algum limite muda mais que 0,005, aumentar para
  `B = 10000`.
- Na campanha real, a reamostragem também preserva os blocos temporais: os blocos são reamostrados dentro dos grupos.
  O procedimento é validado na calibração.

**Valores-p:**
- não inferioridade: `p = (1 + #{b : Δ*_b ≤ −0,02}) / (B + 1)`;
- superioridade: `p = (1 + #{b : Δ*_b ≤ 0}) / (B + 1)`.

**EX-20.**
- `B = 9`, com 2 dos 9 `Δ*` ≤ −0,02 → `p = 3/10 = 0,3`.
- `B = 19`, sem nenhum → `p = 1/20 = 0,05`. Não rejeita a 0,025, o que mostra o piso `1/(B+1)`.

### 13.3 Multiplicidade

- Holm sobre os **3** contrastes primários (H1a, H1b, H2), com α = 0,025 unilateral por família.
- Contraste não executado entra com p = 1.
- As demais comparações são secundárias ou exploratórias, sem ajuste, e rotuladas como tal.

**EX-18.**
- p = (0,004; 0,03; 1,0) → rejeita só o primeiro. O segundo passa de 0,025/2.
- p = (0,001; 0,011; 0,02) → rejeita os três.

### 13.4 Eventos raros e zero

- Limite superior exato unilateral de Clopper–Pearson no nível de **grupo**. Com 0 eventos em n grupos:
  `1 − α^{1/n}`.
- Nunca usar bootstrap degenerado como prova de risco zero.
- Registrar a suposição: grupos independentes.

**EX-19.** Com n = 40 grupos e α = 0,05, o limite é 0,0721575.

### 13.5 Cobertura a 5% de risco seletivo

- Os botões do método (rigor de verificação e, na campanha, θ de variabilidade) são varridos **em cal**.
- Congela-se o valor que maximiza a cobertura com risco seletivo observado ≤ 5% em cal.
- No teste, reportar cobertura e risco observados com IC, mesmo acima da meta (§11.1).

### 13.6 Simulação de precisão (dimensionamento)

- Usar só dev/cal: a distribuição de tamanhos de grupo, as consultas por grupo e a correlação intragrupo das
  diferenças pareadas.
- Simular `n` grupos de teste (grade 100–600) × 1.000 réplicas, com `Δ = 0` verdadeiro.
- Escolher o menor `n` com P(limite inferior de 95% > −0,02) ≥ 0,80.
- Se o orçamento não o permite, declarar H1a **estimativa**, sem alegação de não inferioridade (§4.4).
- Relatar efeitos, IC, número de grupos e custos, não só valores-p.

## 14. Diferenças em relação ao desenho inicial (`docs/design/desenho_inicial.md`)

- **§B4:**
  - variantes κ por (fator, execução) e hipóteses de nível declaradas (4.3);
  - replay sem vínculo usa os níveis declarados (5.4);
  - estado `indeterminado` generalizado (8.3);
  - regra de quando U é necessário (8.4).
- **§B3:** completude da família com inadmissíveis (R07); `D` executado inclui a diferença de variante.
- **§B5:**
  - pontuação total com precedência;
  - célula `incompleta`;
  - `compativel_com_variabilidade` definida no núcleo;
  - lastro por certificados verificáveis (substitui `eval`/`trace`/`logic`);
  - denominadores primários sobre consultas alteradas (R13).
- **§B1:**
  - `v2` inclui o filtro `DX_NAME`; `neg_only` não;
  - `sel` por grupo de `Id` em `per_entity_any` (R30);
  - patches são de estágio `acm` e aparecem como handles opacos.
- **§B2 / §E:** ∅ e `D` contam no orçamento (R08).
- **§C:**
  - os valores de teste citados no desenho ficam queimados (R28);
  - o exemplo de §7.2 não é `test_only`;
  - `V1_TO_V2` fora do conjunto confirmatório de teste (D2).
- **L3 ≡ L2** no núcleo determinístico.

## 15. Índice de exemplos

- **Chaves e presença:** EX-01 (projeções e chave), EX-02 (UNAVAILABLE).
- **Igualdade:** EX-03.
- **Semântica:** EX-04 (`sel`), EX-05 (`occ`), EX-06 (traços).
- **Famílias:** EX-07 (§7.2), EX-08 (cancelamento), EX-09 (interação), EX-10 (não monótono), EX-13 (inadmissível),
  EX-14 (bundle), EX-15 (dummy), EX-16 (BFS e orçamento).
- **Identificação:** EX-11 (divergência HYPOTHETICAL), EX-12 (testemunhas).
- **Lastro, perfis e esquema:** EX-21 (lastro), EX-22 (perfis), EX-23 (validação de saída).
- **Pontuação:** EX-S01 a EX-S35.
- **Métricas e estatística:** EX-17 (métricas), EX-18 (Holm), EX-19 (evento zero), EX-20 (valor-p de NI).
