# SPEC — benchmark de atribuição de mudanças por associação (HealDB)

Versão 0.2 (lead β, 2026-09-30). É a revisão da v0.1 após a GATE 2: segue a auditoria
`docs/auditorias/gate2_spec.md` (A01–A21) e as decisões da sessão principal em `docs/decisoes.md` ("GATE 2"), que
prevalecem sobre a auditoria. As mudanças estão listadas em §16. Implementa o protocolo v0.2
(`docs/protocolo/Protocolo_Experimental_HealDB_Revisado_v0_2.md`). As resoluções **R01…R30** são as de
`docs/analise/00_analise_protocolo.md` §3; os desvios registrados são os D7.x de `docs/deviations.md`.

**Normatividade da semântica do núcleo.** Onde este SPEC descreve o pós-processamento (§1–§3), o normativo é o
comportamento de `src/habench/pipeline/core.py` (lead α), que reproduz as tabelas V1 e V2 com 0 diferenças. As
citações `core.py:NN` apontam as linhas. Se o texto e o núcleo divergirem, vale o núcleo, e o texto deve ser corrigido.

**Fora do escopo deste SPEC** (remissão aos documentos donos, A21):
- métodos B0–B3 e as adaptações de BugDoc e Why-Diff (§10 do protocolo): lead γ;
- estados de afirmação reconstruída (§6.5): `habench.types.ClaimState` e `habench.prov` (lead δ);
- campanha, anotação e Q3 (§9, §12): lead δ;
- a "base de nove combinações" de §8.2 do protocolo aparece aqui só como grade das famílias F e M (§12).

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
| OMS | `ICD-10-WHO` | `hier:<16 primeiros hex do sha256 das tabelas de hierarquia>` (`mapping.py:29`) | código OMS sem ponto, 3 ou 4 caracteres (`E119`) |

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

- Um registro aprovado `unmapped` é contado à parte (`RunResult.unmapped`, `core.py:318`). Ele não gera chave
  própria e não afeta a presença de nenhuma chave: uma chave que nenhum registro aprovado produz é `ABSENT` (1.4),
  mesmo que o registro que a produzia antes tenha virado `unmapped` (A09, EX-27).
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
- `Presence.ABSENT`: a resposta do medicamento é válida (inclusive sem entidades, `STATUS_EMPTY`) e nenhum registro
  aprovado tem essa chave. Registros `unmapped` não mudam isso.
- `Presence.UNAVAILABLE`: não há linha de resposta para o medicamento (`STATUS_MISSING`), ou a resposta é NULL ou
  JSON não decodificável (`STATUS_FAILED`) (`evidence.py:19-22`, `core.py:84-88`). Na campanha, também uma resposta
  com erro de serviço ou truncada. Vale para todas as chaves do medicamento.

Uma consulta `(contraste, a)` é **elegível** só se a presença de `a` é `PRESENT` ou `ABSENT` em x0 e em x1. As
inelegíveis entram no fluxo de elegibilidade, com o motivo, e nunca viram "aparecimento" nem "desaparecimento".

**EX-02.** O medicamento 7 não tem resposta em x0. Em x1, sua resposta produz `E119`. Em x0, a presença de
`(7, E119)` é `UNAVAILABLE`; em x1, `PRESENT`. A consulta é inelegível, não é um "aparecimento".

**EX-27 (`unmapped` não é ausência própria, A09).** Uma entidade com `E11.65` 0,80, preset V1 com `map`
`who_exact_fb` → `who_exact`, espaço OMS. Em x0, a chave `E11` está presente. Em x1, `E11.65` não tem projeção
exata: o registro aprovado vai para `unmapped = {E11.65}` e a chave `E11` fica `ABSENT`. A consulta `E11` mudou, com
família `{{map}}`.

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
3. **Decisão:** igualdade do mapa `AssocKey → Presence` no espaço do contraste (desfecho primário) e, à parte, dos
   atributos de 2.1 (desfechos secundários).

A forma canônica serve só para comparar. O pipeline sempre recebe a resposta original, na ordem original.

### 2.1 Atributos secundários (§5.1 do protocolo, A10)

Definidos só para chaves `PRESENT` nas duas execuções. Valores comparados **exatamente** (floats como `float`, sem
tolerância); tolerâncias só em análises auxiliares rotuladas, nunca para declarar identidade nem esconder cruzamento
de limiar (§5.2 do protocolo).

| atributo | valor | fonte |
|---|---|---|
| `score` | `cs` do melhor registro aprovado da chave (ordem `cs` desc, `es` desc) | `core.py:319-325` (`Attrs.score`) |
| `entity_score` | `es` desse mesmo registro | `Attrs.entity_score` |
| `classe` | V1: `fl_low_confidence = cs < low_conf_thr ou es < low_conf_thr` (0,70). V2: `tp_icd_score` = HIGH se `cs ≥ icd_hi` (0,60), MEDIUM se `cs ≥ 0,30`, senão LOW | F1 §2.2; `mapa_codigo_healdb.md` §2 |
| `granularidade` | no espaço OMS, comprimento do código (3 = categoria, 4 = subcategoria). Há **mudança de granularidade** quando `k` (4 caracteres) está presente numa execução e ausente na outra, e `k[:3]` está presente na outra. Relação ancestral válida só pela hierarquia fixada | §5.1 do protocolo |

Métricas: contagens descritivas de chaves com atributo alterado, por família de cenário e origem. A atribuição de
mudanças de atributo usa a mesma maquinaria de §6 com `state` categórico; é **secundária e exploratória**, e só nela
os botões `low_conf_thr` e `icd_hi` entram em `D`.

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
- `Id` (se ausente, `pos + 1`, `evidence.py:188`);
- `Type`;
- `Score` (`es`);
- `Traits`: pares (`Name`, `Score`); um score ausente conta como 0 nas comparações de HYPOTHETICAL;
- `ICD10CMConcepts`: pares (`Code`, `Score` = `cs`), em ordem.

Entidade sem conceitos não gera candidato, mas seus traços contam para o seu grupo de `Id` em `per_entity_any`.

**Grupo de `Id`:** as entidades do mesmo medicamento com o mesmo `Id`. Nos dados reais há `Id` repetido (R30).

### 3.2 Etapas, em ordem

1. **Patches.** Aplicar os patches presentes no híbrido (§4.5).
2. **Candidatos.** Para cada entidade, na ordem do array, e para cada conceito, na ordem, um candidato
   `c = (pos, eid, code, rank, es, cs, traits, type)`, na **ordem de emissão**. `rank` é a posição do conceito na
   lista da entidade (0 = primeiro); só aparece no traço e não é usado por nenhuma regra.
3. **`sel`** (`core.py:98-113`, A02).
   - `all` mantém tudo.
   - `top1` trabalha sempre por **grupo de `Id`**, qualquer que seja o nível de `occ`:
     1. dentro do grupo, para cada código, fica só o **último** candidato desse código na ordem de emissão;
     2. entre esses, fica o de menor chave `(−cs, collation_key(code))`, onde `collation_key` imita a ordenação
        MySQL `utf8mb4_0900_ai_ci` (`evidence.py:27-45`: `_` e `.` antes de dígitos, dígitos antes de letras, letras
        sem distinção de caixa).

     Resta um candidato por grupo de `Id`. Como os códigos restantes são distintos, não há outro desempate. A
     auditoria propôs `(cs desc, code asc, posição asc)` sobre todos os candidatos do grupo; o núcleo difere dela no
     passo 1 (o último candidato de cada código) e na ordenação por colação, e **o núcleo prevalece**.
4. **`occ` (registros)** (`core.py:116-171`). Os candidatos mantidos por `sel` são percorridos na ordem de emissão.
   - `last_upsert`: um registro por `code`. `es`, `cs` e `type` vêm do **último** candidato do código. Os traços são
     a união dos traços das entidades dos candidatos do código, e o score de cada nome vem do último candidato cuja
     entidade tem esse nome.
   - `first_upsert`: igual, mas com o **primeiro** candidato, para scores, tipo e traços.
   - `per_entity_any`: um registro por `(eid, code)`. `es`, `cs` e `type` vêm do último candidato do par. Os traços
     são os de **todas** as entidades do grupo de `Id` (inclusive as sem conceitos ou cujos candidatos `sel`
     descartou), com o score do último na ordem do array (upsert da V2 em `(med, Id, nome)`, `core.py:134-139`).
5. **Predicados por registro** (`core.py:244-260`, todos avaliados, sem curto-circuito). O registro é aprovado se
   passa em todos:
   - `trait` (tabela de 3.3);
   - `ent_thr`: `es ≥ t` (variante `alt`: `es > t`, só no universo de §8);
   - `icd_thr`: `cs ≥ t` (idem);
   - `map`: o **portão** do nível (1.2) tem de aprovar o código. Em `cm_gated` é o portão V1; em `cm_ungated` não há
     portão; nos níveis `who_*` o portão é "a projeção do próprio nível existe".
6. **Chave e presença.** Cada registro aprovado recebe a chave no espaço do contraste (1.3). Registro aprovado sem
   chave no espaço vai para `unmapped` (só acontece com `cm_ungated` no espaço OMS). A presença é a de 1.4.

**Traço de decisão** (`core.py:360-385`; materializado em L2-M e devolvido por `evaluate`, §7): os candidatos (com
`selected`), e por registro a chave, os membros, o candidato-fonte, `es`, `cs`, os traços e uma decisão por estágio.
Neste SPEC, `verdict ∈ {pass, fail}` e `failed ⊆ {trait, ent_thr, icd_thr, map}` resumem essas decisões: `trait`
reprova se qualquer estágio de traço (`trait_veto`, `trait_hyp`, `trait_required`, `trait_type`) reprova. `failed`
lista **todos** os predicados que reprovaram.

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
- `sel = top1` → `{E11.9, J45.0}` (empate de `cs` resolvido pela colação do código: `J45.0` antes de `R50.9`).

**EX-05 (`occ`).** Cinco entidades `DX_NAME`, com `Id` distintos. "–" na coluna de traços significa o traço
padrão DIAGNOSIS 0,90 (A21):

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

**Níveis de teste** (R28, D7.5, A20).
- Só `ent_thr` e `icd_thr` têm níveis de teste próprios. Os fatores categóricos (`occ`, `sel`, `trait`, `map`) não
  têm: a novidade do teste vem dos grupos de teste e das combinações de contraste não usadas em dev/cal.
- **Geração da lista selada, no congelamento P4:** grade de valores com passo 0,005 em [0,50; 0,75], menos todo valor
  queimado (citado em `docs/design/`, neste SPEC ou nos exemplos, inclusive 0,575 e 0,625 do desenho §C) e menos os
  níveis de dev/cal; sorteio de 4 valores com semente gerada no congelamento. O SHA-256 da lista (JSON canônico, com
  a semente) é publicado no registro de congelamento; o conteúdo fica só no pacote de verdade.
- Nos contrastes de teste, o nível x0 dos limiares é o do preset V1 (0,60), salvo contraste que declare outra base de
  dev/cal; os níveis selados entram como nível x1.

### 4.2 Limite de fatores

Cada contraste tem no máximo **6 fatores binários** em `D` (§7.3). Um fator é binário no contraste: nível de x0
contra nível de x1. Um bundle declarado conta como um fator (4.4).

### 4.3 Variantes de implementação (espaço K)

Uma **variante** descreve como o código que implementa um nível pode de fato se comportar. Nas execuções do
benchmark as variantes são `std`, exceto nas execuções da família I que realizam `alt` (abaixo). No universo de
identificação (§8), as variantes representam a incerteza sobre o código quando ele não pode ser executado nem
inspecionado por traço.

| fator, nível | `std` | `alt` | origem da hipótese (A07) |
|---|---|---|---|
| `ent_thr`, `icd_thr` (qualquer t) | `≥ t` | `> t` | V1 usa `≥ 0,6` (F1 §2.3, passo 4); o `link` da era `map` (0e43ed9) usava `> 0,7` (`mapa_codigo_healdb.md` §0; não está em F1) |
| `trait = v1` | veto em `hyp > 0,65` | veto em `hyp > 0,60` (≡ `v1_hyp_le_0.6`) | divergência documentação × código, F1 §6 item 2 |
| `occ = last_upsert` | último candidato | primeiro candidato (≡ `first_upsert`) | "vale a última ocorrência" depende do upsert `ON DUPLICATE KEY UPDATE`, F1 §2.2; o gerador de `extend` nunca foi commitado, F1 §2.4 |
| `map = cm_gated` | com portão | sem portão (≡ `cm_ungated`) | `extend` é a md sem o portão, F1 §1 e §2.3 |
| demais | única | – | – |

Só o `>` dos limiares é comportamento novo; as outras variantes `alt` repetem o comportamento de um nível par. O
modelo é decisão registrada (D7.7), com duas condições (decisões GATE 2, item 3):
- H1b é relatada também com `K = ∅` (sem variantes `alt`), como sensibilidade pré-declarada;
- parte das execuções novas da família I **realiza** a variante `alt`: o código executado tem o rótulo do nível
  (por exemplo `trait = v1`) e o comportamento `alt`. Assim as duas histórias ocorrem de fato, e a verdade dessas
  execuções usa a variante `alt`.

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
- **Regras de referência** (`pipeline/semantics.py`, lead α). São corretas, mas incompletas: devolvem `None` quando
  não decidem, e nunca `False`. Leem só a evidência do medicamento de `a` e a hierarquia; não executam híbridos.
  - **Variantes de patch.** Cada regra é aplicada à evidência de `a.med` em **todo** subconjunto dos patches do
    contraste que editam esse medicamento, e só certifica se valer em todos (isso cobre `D` com `patch:*` que alterem
    `es`, `cs` ou traços de candidatos de `a`, A02).
  - **Candidatos relevantes de `a`:** os candidatos de `a.med` cujo código projeta para a chave de `a` em algum dos
    níveis de `map` do contraste. **Pool de entidades:** as entidades desses candidatos mais todas as entidades dos
    seus grupos de `Id`.
  0. **Triviais:** `f ∉ D` → irrelevante; medicamento `UNAVAILABLE` → irrelevante; `patch:<id>` que não edita
     `a.med` → irrelevante; outro `patch:*` ou fator `prep`/`acm` → `None`.
  1. **Limiar** (`ent_thr` com níveis t0, t1): irrelevante se nenhum candidato relevante tem `es` em
     `[min(t0,t1), max(t0,t1))`. `icd_thr`: o mesmo com `cs`.
  2. **`sel`:** irrelevante se todo candidato relevante é o candidato mantido por `top1` no seu grupo de `Id`
     (3.2 passo 3). Não usa `rank`: com `Id` duplicado, o candidato pode ser o primeiro da sua entidade e não o do
     grupo (A02, EX-25).
  3. **`occ`:** irrelevante se os candidatos relevantes têm códigos distintos **e** `Id` distintos, **e** cada um
     desses `Id` pertence a uma única entidade. Então cada registro de `a` tem um só membro e os mesmos traços sob
     qualquer nível de `occ` (EX-26).
  4. **`map`:** irrelevante se, para todo código da evidência, "passa no portão e projeta para a chave de `a`" tem o
     mesmo valor nos dois níveis. Inclui `cm_gated` × `who_exact_fb` no espaço OMS (1.3).
  5. **`trait`:** irrelevante se, para todo subconjunto não vazio do pool de entidades (união dos nomes de traço; cada
     score de HYPOTHETICAL presente, ou nenhum) e todo tipo de candidato relevante, as duas regras de 3.3 dão o mesmo
     veredito. Pool com mais de 10 entidades → `None`.

  Mudanças em relação à v0.1: regra 1 sobre as variantes de patch; regra 2 pelo `top1` do grupo de `Id` (não pelo
  `rank`); regra 3 com `Id` único; regra 4 generalizada; regras 0 e 5 novas. O lead α valida as regras com um teste
  de solidez por propriedade contra força bruta, com `Id` duplicado.
- **Monotonicidade.** A única propriedade assumida: baixar um limiar só pode fazer uma associação passar de ausente
  para presente, com os outros fatores fixos. Nada mais é monótono. A suficiência `S ↦ state_S(a)` é medida como não
  monótona.

**EX-15.** No contraste por componentes de EX-14, as regras certificam `sel`, `map`, `ent_thr` (nenhum `es` em
[0,60; 0,70)), `icd_thr` (nenhum `cs` em [0,30; 0,60)) e `trait` (regra 5: em todo subconjunto de {e1, e2}, `v1` e
`v2` concordam, porque NEGATION veta nas duas e DIAGNOSIS com tipo `DX_NAME` passa nas duas). `occ` não é
certificado (C61 tem dois candidatos) e de fato não é irrelevante.

**EX-25 (`Id` duplicado, contraexemplo de `sel`, A02).** Duas entidades com `Id` 1: e1 com `C61` 0,90 e e1′ com
`E11.9` 0,95; `trait = v2`, `occ = per_entity_any`, espaço CM; `sel`: `all` → `top1`. C61 vai de presente a ausente,
porque o `top1` do grupo `Id` 1 é `E11.9`. A regra 2 da v0.1 (por `rank` na entidade) certificaria `sel`; a regra 2
atual devolve `None`.

**EX-26 (`Id` duplicado, caso de `occ`, A02).** A mesma evidência, com `sel = top1` e `occ`: `last_upsert` →
`per_entity_any`. Como o `top1` é sempre por grupo de `Id` (3.2), C61 é descartado nos dois níveis e fica ausente:
`occ` é de fato irrelevante. O contraexemplo de `occ` da auditoria dependia do `top1` por entidade da v0.1 e não se
realiza no núcleo. Ainda assim, a regra 3 devolve `None` (o `Id` 1 tem duas entidades): correta, mas incompleta.

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
  executado. Sem ele, usa os níveis declarados de d0 e d1.
- **Variante de um nível no replay** (A21): cada fator usa a variante que o ambiente real tem para o nível usado. Nas
  execuções do benchmark é a variante da execução de onde o nível vem (`std`, ou `alt` nas execuções da família I que
  a realizam). No universo de §8, é `κ0(f)` para nível tomado de x0 (ou d0) e `κ1(f)` para nível tomado de x1 (ou d1),
  mesmo que o nível declarado não tenha sido executado.
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
4. **Completude** (A13): a família achada é completa se o orçamento não acabou **e** todo `S` pulado por ser
   inadmissível contém propriamente algum suficiente achado (a condição de 6.1). Senão é marcada incompleta, mesmo sem
   esgotar o orçamento (EX-28).

- Todo `S` avaliado teve os seus subconjuntos próprios avaliados ou podados, então todo suficiente achado é mínimo
  mesmo sem monotonicidade.
- Se o orçamento acaba no meio, o resultado é uma família parcial verificada, marcada incompleta.
- Os certificados dummy usados na poda são os das regras de referência de 4.6, aplicáveis só se a vista mostra a
  evidência (resposta completa ou top-1); em L1 não há poda por dummy.
- Com várias consultas num contraste, a busca é conjunta: `S` só é pulado se é podado para **todas** as consultas
  ainda abertas.

**EX-16.** `D = {A, B, C}`, suficientes `{A}`, `{A,C}`, `{B,C}` e `{A,B,C}`.
- Orçamento ilimitado: avalia ∅, D, A, B, C e BC, em 6 avaliações. `F = {{A},{B,C}}`, completa.
- Orçamento 5: para antes de BC, com `{{A}}` parcial e incompleta.

**EX-28 (BFS com inadmissíveis, A13).** `D = {A, B, C}`.
- (a) `{A}` inadmissível; suficientes entre os admissíveis: `{B,C}` e `D`. A BFS avalia ∅, D, B, C, AB, AC e BC (7),
  acha `{{B,C}}` e marca **incompleta**: `{A}` foi pulado e não contém nenhum suficiente.
- (b) `{A,B}` inadmissível; suficientes: `{A}`, `{A,C}` e `D`. A BFS avalia ∅, D, A, B, C e BC (6), acha `{{A}}` e
  marca **completa**: `{A,B}` contém `{A}`.

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

  Células N1/N2 × capacidade (A21): em R-A, `evaluate(S)` com `S` não expressável levanta `Unavailable` e custa 0;
  R-B ≡ R-A no núcleo local (7.3); em R-C não há replay.

### 7.2 Ablações e perdas combinadas

| id | remove de L2-R/L2-M | efeito no replay (R29) |
|---|---|---|
| A1 | `submitted_text` | nenhum para fatores pós-ACM. Sem texto, híbridos com fatores de preparação ficam inadmissíveis |
| A2 | `acm_response` completa, mantendo só o conceito top-1 por entidade | o broker replica sobre a evidência top-1 e o replay pode não validar |
| A3 | `code_link` | o broker replica com os níveis **declarados** (5.4) |
| A4 | `env_versions` | nenhum (o broker usa o ambiente real). O método não sabe a versão da terminologia |
| A5 | `ops_actions` | nenhum para presença |
| A6 | do `trace` (só em L2-M), tudo o que não é o candidato vencedor de um registro aprovado: os candidatos descartados por `sel`, os membros não vencedores (sobrescritos pelo upsert) e os registros reprovados (A11). Fica `trace_winners`: por registro aprovado, o candidato-fonte e as decisões | nenhum |

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
- **H1a primário** usa `b = 16`, o regime restrito de §10.2 do protocolo, onde o material armazenado de L2-M pode
  poupar avaliações; 32 e 64 são secundários (R09, A05, D7.9).
- `evaluate` devolve também o traço do híbrido. Esse traço conta como pago e pode lastrear certificados `trace` em
  qualquer vista (9.2).
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

- `W(v, r) = { F(h′) : h′ ∈ U ∪ {h*}, o_{v,r}(h′) = o_{v,r}(h*) }`, onde `h*` é a história verdadeira. A união com
  `{h*}` garante `F* ∈ W` mesmo quando `h*` não é representável em U (por exemplo, `a` com mais candidatos que `L`;
  A01). Histórias sem mudança de `a` têm observação diferente de `h*` (os finais diferem) e nunca entram.

### 8.2 Universo declarado U (β3 implementa)

- **Símbolos de candidato:** (faixa de `es`, faixa de `cs`, `top1`, classe de traço, classe de tipo, classe de `map`).
  - As faixas de score são cortadas nos níveis de x0 e x1 dos fatores de limiar em `D`, com um ponto "exatamente no
    limiar" por causa da variante `gt`.
  - A classe de traço é (NEG, LOW_CONFIDENCE, PERTAINS_TO_FAMILY, faixa de HYP ∈ {nenhum, ≤ 0,60, (0,60; 0,65],
    > 0,65}, presença de DXS).
  - A classe de tipo é DX_NAME ou outro.
  - A classe de `map` é relativa à chave de `a` (A21): para cada nível de `map` do contraste, se o código passa no
    portão e projeta para a chave de `a` por correspondência exata (subcategoria, ou categoria de 3 caracteres igual
    ao código), por fallback de prefixo, ou não projeta para ela.
  - Símbolos com a mesma assinatura de comportamento (o mesmo vetor aprovado/reprovado sobre todos os híbridos e
    variantes) são fundidos.
- **Bundle de candidatos:** sequência ordenada de até `L = 4` símbolos, com a partição em entidades. A ordem importa
  por `occ`.
- **Níveis e variantes:** as hipóteses de 4.3, com no máximo 3 fatores alterados.
- **Expansão** em largura por comprimento, deduplicando por classe `(tabela-verdade, observação)`. `saturated` =
  passar de `L−1` para `L` não criou classe nova.
- **Cortes de recurso** (A01, A15): a expansão tem orçamento por consulta (tempo e memória, fixados em dev na β3).
  Qualquer corte, por orçamento, por limite de símbolos ou por `L`, conta como **não saturado**.

### 8.3 Limites e estado de identificação

- **`W_hi`:** famílias das classes de `U ∪ {classe(h*)}` com a mesma observação **marginal** em `a` que `h*`. As
  demais associações ficam livres. Por construção, `F* ∈ W_hi`.
- **`W_lo`:** `{F*}` mais as famílias das classes **que já contribuem para `W_hi`** cuja testemunha **se eleva** ao
  grupo verdadeiro:
  1. substituir os candidatos de `a` na evidência real pelo bundle da testemunha, preservando as invariantes de 4.5;
  2. reexecutar;
  3. exigir que a observação marginal de `a` **e** toda observação visível do resto do grupo (finais das outras
     chaves, traços, replay) fiquem inalteradas.

  Assim `F* ∈ W_lo ⊆ W_hi` vale por definição (A01).
- **Saturação efetiva:** U conta como saturado para a consulta só se a expansão saturou (8.2) **e** `classe(h*) ∈ U`.
- **Estado:**
  - `identificado`: `W_lo = W_hi = {F*}` e U saturado.
  - `ambiguo`: `|W_lo| ≥ 2`. Existem duas testemunhas, então a ambiguidade está demonstrada mesmo sem saturação.
  - `indeterminado`: `|W_lo| = 1` e (`|W_hi| > 1` ou U não saturado). É reportado e excluído dos denominadores
    primários.

  **Partição.** Como `F* ∈ W_lo`, vale `|W_lo| ≥ 1`. Se `|W_lo| ≥ 2`, o estado é `ambiguo`. Se `|W_lo| = 1`, então
  `W_lo = {F*}`: ou `W_hi = {F*}` e U saturado (`identificado`), ou não (`indeterminado`). Os três casos são
  exaustivos e disjuntos.

**EX-24 (`h* ∉ U`, A01).** O cenário de EX-12, mas com U sem a evidência verdadeira `(0,58; 0,90)`.
- L1 × R-C: `W_hi = W_lo = {{{ent_thr}}, {{icd_thr}}, {{ent_thr, icd_thr}}}` → `ambiguo`. Sem a união com `{h*}`,
  `W` seria só `{{{icd_thr}}, {{ent_thr, icd_thr}}}` e não conteria `F*`.
- L2-R × R-C: `W_lo = W_hi = {F*}`, mas `h* ∉ U` → não saturado → `indeterminado`.
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

A saída traz certificados `(kind, S ou f, valor)`. Cada um é avaliado no contexto da **execução** do método: método ×
vista × capacidade × orçamento × contraste, com o log de `evaluate` do `Env` dessa execução.

| `kind` | afirma | aceito quando (A03) |
|---|---|---|
| `final` | `suff(∅) = falso` ou `suff(D) = verdadeiro` | sempre, só para `S ∈ {∅, D}` (finais observados) |
| `eval` | `suff(S)` = valor | `S` consta do log de `evaluate` desta execução (logo só em R-A/R-B) |
| `trace` | `suff(S)` = valor, lido do traço de `h_S` (o `state` de `a` em `h_S` é "presente" se e só se o traço tem registro aprovado com a chave de `a`) | (i) em L2-M, para `S ∈ {∅, D}`, com os traços armazenados de x0 e x1 (também sob A6: os vencedores bastam para o estado); (ii) em qualquer vista, para `S` que consta do log de `evaluate` (o traço devolvido já foi pago; D7.9) |
| `dummy` | `f` irrelevante para `a` (4.6) | a vista mostra a evidência (`acm_response` ou `acm_response_top1`): L2-*, N1, N2; nunca em L1 |

A derivação por traço é só essa leitura do estado em `h_S`. A regra fechada proposta pela auditoria ("registro único
com `failed = {f}` em x0 e aprovado em x1, com os demais fatores dummy ⇒ `suff({f})`") não é um tipo à parte: ela
decorre de `final` + `dummy` pela cobertura módulo irrelevantes do passo 3.

O avaliador:
0. **Descarte** (A03). Traduz handles para nomes canônicos e intersecta cada `S` com `D` executado (o mesmo vale para
   os `S` do log). Descarta, com o motivo registrado, todo certificado não aceito pela tabela acima: `eval` fora do
   log, tipo indisponível na célula, `final` com `S ∉ {∅, D}`. Descartados não contam para nada.
1. Confere **cada** certificado restante contra a tabela-verdade: o valor real, não o que o broker devolveu. Um
   certificado falso → `errado` (em qualquer célula, A14).
2. Seja `Z` o conjunto de fatores com `dummy` verdadeiro aceito. Como `state_S = state_{S∖Z}`, cada certificado de
   `S` vale para toda a classe `{S′ : S′∖Z = S∖Z}`.
3. **Cobertura:** todo `S ⊆ D` tem de ter `S∖Z = T∖Z` para algum `T` certificado, ou `S∖Z ⊋ T∖Z` para algum `T`
   certificado suficiente.
4. Sem cobertura, a saída não tem lastro → `indevidamente_exclusivo`.

**EX-21.** Tabela-verdade de EX-10, afirmação `{{ent_thr}}`.
- (a) `final` para ∅ e D, e `eval` para `{ent_thr}` (suf.), `{icd_thr}`, `{patch:p3}` e `{icd_thr, patch:p3}`
  (insuf.): coberto e verdadeiro → lastro.
- (b) Sem `{icd_thr, patch:p3}`: sem cobertura.
- (c) Com `eval {ent_thr, icd_thr}` suficiente: afirmação falsa.
- (d) `dummy(icd_thr)` no lugar das avaliações com `icd_thr`: cobre, mas o certificado é falso (`{ent_thr}` é
  suficiente e `{ent_thr, icd_thr}` não) → errado.

Os casos (a)–(d) são em L2-R × R-A, com todos os `S` avaliados no log. Casos de descarte (A03):
- (e) Os certificados de (a), mas o log não tem `{icd_thr, patch:p3}`: o `eval` desse `S` é descartado e a
  cobertura falha, como em (b).
- (f) L2-R × R-A, com `trace` de `{icd_thr, patch:p3}` e esse `S` fora do log: descartado; sem cobertura.
- (g) Idem, com `{icd_thr, patch:p3}` no log: o `trace` é aceito e cobre.
- (h) L2-R × R-C: todos os `eval` de (a) são descartados (não há log); restam os `final`; sem cobertura.

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
| `ambiguo` | certificado falso → errado; `F = F*` → indevidamente exclusivo (acerto por acaso); senão → errado |
| `incompleta` | certificado falso → errado; `F = F*_adm` → indevidamente exclusivo; senão → errado |
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

A **necessidade** de um contraste é o número de avaliações da BFS conjunta de referência (6.3), com a poda por
dummy de referência quando a vista mostra a evidência. Quando a capacidade não executa híbridos (R-C, ou N1/N2 sem
nenhum `S` expressável), a necessidade é **0**, e `orcamento_esgotado` é sempre desnecessária (A13). Não se usa
`+∞`, que tornaria a abstenção apropriada.

**Orientação aos métodos** (A21): `contrafactual_indisponivel` só é apropriada quando falta a resposta armazenada
para um híbrido (célula `incompleta`). Em R-C, a falta de replay pede `informacao_insuficiente` ou `alternativas`.

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
| EX-S36 | ambíguo, `W_lo = W_hi = {F1, F2}` | V(F1), com um certificado falso | errado (A14) |
| EX-S37 | ambíguo, necessidade 6, `b` = 64 | orçamento esgotado | abstenção desnecessária |
| EX-S38 | ambíguo | contrafactual indisponível | abstenção desnecessária |
| EX-S39 | ambíguo | falha de execução | falha |
| EX-S40 | incompleta | compatível com variabilidade | errado |
| EX-S41 | incompleta, necessidade 6, `b` = 4 | orçamento esgotado | abstenção apropriada |
| EX-S42 | incompleta | falha de execução | falha |
| EX-S43 | inalterado | orçamento esgotado | abstenção desnecessária |
| EX-S44 | inalterado | contrafactual indisponível | abstenção desnecessária |
| EX-S45 | inalterado | falha de execução | falha |
| EX-S46 | indeterminado, `W_lo = {F1}`, `W_hi = {F1, F2}` | A({F1, F2}) | excluído |
| EX-S47 | idem | ausência de mudança | excluído |
| EX-S48 | idem | compatível com variabilidade | excluído |
| EX-S49 | idem | informação insuficiente | excluído |
| EX-S50 | idem | orçamento esgotado | excluído |
| EX-S51 | idem | contrafactual indisponível | excluído |
| EX-S52 | idem | falha de execução | falha |
| EX-S53 | identificado, R-C (necessidade 0), `b` = 16 | orçamento esgotado | abstenção desnecessária |

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

**Por que a cobertura primária usa só as alteradas** (R13, A18, D7.1). No núcleo determinístico, os finais de x0 e
x1 revelam se `a` mudou. Pôr `Q_u` no denominador inflaria a cobertura com casos triviais, e as falsas atribuições em
`Q_u` já são medidas pelo controle nulo (§11.2 do protocolo). A justificativa **não vale na campanha**: sob
variabilidade, `Q_u` deixa de ser trivial, e a cobertura sobre `Q_u` passa a ser relatada ao lado da primária.

### 10.2 Primárias

Estimadores de razão agregados por consulta, com inferência por grupo (§12):
- `cobertura = #correto_sustentado(Q_c) / |Q_c|`. `falha` fica no denominador como não coberta.
- `cobertura_bruta = #categóricas(Q_c) / |Q_c|`.
- `risco_seletivo = (#errado + #indevidamente_exclusivo) / #categóricas`, sobre `Q_c ∪ Q_inc` (literal, §11.1).
- `risco_comprometido = (#errado + #indevidamente_exclusivo) / #(categóricas − nao_comprometido)`, sobre
  `Q_c ∪ Q_inc` (A04, D7.8). Uma lista longa de `alternativas` é `nao_comprometido` e diluiria o risco literal sem
  ganhar cobertura; por isso a calibração a 5% (13.5) e a guarda de H1b (13.1) usam o risco comprometido. Os dois
  riscos são sempre relatados. Com denominador zero, o risco é 0 (nenhuma saída comprometida, nenhum erro).
- **Controle nulo:**
  - a referência de cada consulta N é a do oráculo, não presumida (A21): N(a)–N(c) só entram como nulos se o
    oráculo dá `inalterado` para todas as suas consultas; um contraste N com consulta alterada é erro de geração e
    sai da família, com contagem;
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
- `risco_seletivo` = 2/4 = 0,5; `risco_comprometido` = 2/3 (q5 é `nao_comprometido`);
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
| N | (a) Só metadados de transporte mudam: `D = ∅`, respostas iguais no nível 2. (b) Só fatores certificados dummy: `map` no espaço OMS, um limiar movido numa faixa vazia. (c) Repetição real: medicamentos do grupo com o mesmo texto enviado. (d) Estocástico: só simulador, reportado à parte. Referência esperada: tudo `ausencia_de_mudanca`, **confirmada pelo oráculo** consulta a consulta (10.2, A21). Distinguir nulo local de nulo prospectivo. | 3 |
| F | Um fator por contraste: `ent_thr`, `icd_thr` ou `trait`, com níveis de 4.1. Patches de borda levam um score exatamente a `t` e a `t − 1e-9`. Referência típica: famílias unitárias. | ~7 |
| M | Pares de `map` com a terminologia fixa. `unmapped` é preservado. Mudança de granularidade sinalizada por relação ancestral válida. `EXTEND` no espaço CM. | ~5 |
| O | `occ` × `sel`, mais `first_upsert`. Preferir grupos com alta multiplicidade de candidatos. Um patch opcional troca posições de entidades. | ~5 |
| X | (i) O bundle real `V1_TO_V2`, nas duas granularidades; nos grupos de teste fica fora do conjunto confirmatório (D2). (ii) Amostragem com rejeição guiada pelo oráculo: k de 3 a 6 fatores, ao menos um sem efeito verificado e ao menos um par oposto, com cotas de forma (unitária, vários conjuntos, interação, não monótona) fixadas em dev/cal. (iii) O exemplo de §7.2 como caso semissintético, **só em dev/cal** (é público; A12, D7.10). | ~6 |
| I | As mesmas execuções de F/M/O/X cruzadas com L1, L2-R, L2-M, A1–A6, C1–C4 e R-A/R-B/R-C, com as células n/a e as equivalentes de 7.3. Execuções novas só para divergência declarado ≠ executado (regra HYPOTHETICAL, portão, `occ`) num subconjunto de F/X. | – |
| P | **Só catalogada** (R20). Preparação: duplicação da indicação, `<drug>`, "with or without", corte. Sem chamadas novas nem simulador nesta fase, toda instância tem referência `contrafactual_indisponivel` e não entra em nenhum denominador. O catálogo registra os fatores e a divergência real da V2 (E14). | – |

## 13. Plano de análise estatística (§11.3; R09, R15–R18, R27)

R24 (origem do piloto de anotação) é do Q3 e fica fora deste SPEC (proposta ao lead δ).

### 13.1 Estimandos

Todos na população de contrastes de teste da família indicada, com o mesmo método M:

| hipótese | estimando | região | teste |
|---|---|---|---|
| H1a (A05, D7.9) | `Δa = cob(L2-R) − cob(L2-M)` | R-A, **`b = 16`** (32 e 64 secundários); famílias F, M, O, X, sem X(i) em teste nem X(iii) | não inferioridade a −0,02 |
| H1b (R17, A06) | `Δb = cob(com evidência efetiva) − cob(sem ela)`, estimador de razão **conjunto por consulta** sobre dois estratos pré-declarados da família I; cada estrato é secundário | divergência: L2-R × (L2-R − A3), em R-A; perda de replay: L2-M × L2-R, em R-C | superioridade (`Δb > 0`), com a guarda `risco_comprometido(com) − risco_comprometido(sem) ≤ +0,02` no percentil 97,5 do bootstrap. Se a guarda falha, H1b não é sustentada |
| H2 (R18) | composto: (i) fração de grupos nulos com falsa atribuição, L3 < L2 (superioridade); **e** (ii) `cob(L3) − cob(L2) > −0,02` (não inferioridade), na campanha pertinente | – | interseção-união: `p_H2 = max(p_i, p_ii)` (A08) |

**H1a** (A05, D7.9):
- Em L2-R valem certificados `trace` derivados dos traços devolvidos por avaliações do log (9.2). Com eles, e com
  `b ≥ 2`, L2-R alcança o que L2-M armazena; no núcleo determinístico `Δa ≡ 0` é esperado.
- **Identidade por construção.** Se todo `Δ*_b` é 0 (variância zero), o resultado é relatado como "identidade por
  construção" e **não** como evidência de não inferioridade: não se relata o valor-p `1/(B+1)` como rejeição.
- **Armazenamento e tempo** (critério descritivo pré-declarado, §11.4): razão de bytes deduplicados L2-R / L2-M por
  contraste, agregada por grupo, com IC bootstrap de 95% (13.2); e tempo de reconstrução (CPU de `evaluate` dos
  híbridos em L2-R contra a leitura dos traços em L2-M), com mediana e IC. Não há limiar de sucesso.

**H1b** (A06, D7.7, D7.8):
- **Denominador comum aos dois braços:** consultas alteradas com família completa e fora de `indeterminado` **nos
  dois** braços pareados. Uma consulta `indeterminado` num braço sai dos dois.
- Relatar `|Q_ind|` por braço, e uma sensibilidade que conta `indeterminado` como não coberto (denominador: todas as
  alteradas com família completa).
- Estimador de razão conjunto: soma de `correto_sustentado` sobre soma de consultas, nos dois estratos juntos.
- **Guarda:** percentil 97,5 dos `Δrisco*_b` ≤ +0,02, com o risco comprometido (10.2). Numa reamostra em que um braço
  não tem categóricas comprometidas, o risco desse braço é 0.
- A1 fica fora dos estratos: a família P é só catalogada (D7.2).
- Sensibilidade pré-declarada: H1b também com `K = ∅` (4.3, D7.7).

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

**Valores-p (R16):**
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

- α = 0,025 unilateral (A08), o mesmo das inferências primárias: o limite é um IC unilateral de 97,5%.

**EX-19.** Com n = 40 grupos e α = 0,025, o limite é `1 − 0,025^{1/40}` = 0,0880973.

### 13.5 Cobertura a 5% de risco seletivo

- Os botões do método (rigor de verificação e, na campanha, θ de variabilidade) são varridos **em cal**.
- Congela-se o valor que maximiza a cobertura com **risco comprometido** (10.2) observado ≤ 5% em cal (A04, D7.8).
- No teste, reportar cobertura, risco comprometido e risco literal observados com IC, mesmo acima da meta (§11.1).

### 13.6 Simulação de precisão (dimensionamento)

- Usar só dev/cal: a distribuição de tamanhos de grupo, as consultas por grupo e a correlação intragrupo das
  diferenças pareadas.
- Simular `n` grupos de teste (grade 100–600) × 1.000 réplicas, com `Δ = 0` verdadeiro.
- Escolher o menor `n` com P(limite inferior a `1 − 0,025/3` > −0,02) ≥ 0,80: o nível do pior caso de Holm (A08).
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
