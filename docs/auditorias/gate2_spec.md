# Auditoria GATE 2 — SPEC v0.1 (lead β)

- **Objeto:** `docs/SPEC.md`, `tests/data/spec_examples.json` e `tests/test_spec_examples.py`, no commit `9890669`
  (branch `audit-gate2`).
- **Referências:** protocolo v0.2, `docs/analise/00_analise_protocolo.md`, `docs/design/desenho_inicial.md`,
  `docs/decisoes.md`, `docs/deviations.md` e `docs/status/lead-beta.md`.
- **Auditor:** sessão Opus independente. Não escrevi o SPEC e não editei nada além deste arquivo.
- **Data:** 2026-09-30.

## 0. O que foi executado

- `uv run pytest tests/test_spec_examples.py -q` → `62 passed`.
- **Recomputação à mão:**
  - EX-01, EX-04 a EX-10, EX-11 (as seis linhas de `W`), EX-12 a EX-21, e EX-17 a partir das 11 consultas do JSON.
  - Da tabela 9.3, EX-S04, S12, S15, S16 e S18, as linhas de `alternativas`, que têm as regras mais delicadas.
  - Todos os valores recomputados conferem.
- **Conferidos só pelo teste:** EX-02, EX-03, EX-22, EX-23 e as demais linhas EX-S.
- **Sonda descartável** (`/tmp`, fora do repositório), que importa as funções de referência do teste:
  - BFS de 6.3 sem orçamento, com conjuntos inadmissíveis aleatórios, contra a família mínima ingênua. Foram 20.000
    tabelas-verdade aleatórias, 12.393 delas não monótonas: **0 divergências**.
  - BFS com orçamento aleatório: nenhum membro de família parcial deixou de ser mínimo (0 de 20.000).
  - Regras dummy 2 e 3 de 4.6 com `Id` duplicado: **as duas são falsas** (A02).

## 1. Achados

Severidades: **bloqueante** (tem de ser corrigido antes de β3 implementar), **importante** (tem de ser corrigido antes
do congelamento P4) e **menor**.

### A01 — bloqueante — §8.3 e §8.2: `W_lo ⊆ W_hi` e a partição dos estados não estão garantidas

- **Problema.**
  - `W_hi` é calculado só sobre as classes de U. A história verdadeira `h*` só está em U se:
    - os candidatos de `a` cabem num bundle de até `L = 4` símbolos;
    - a fusão de símbolos preserva o comportamento do grupo real.
  - Basta que `a` tenha 5 candidatos para que `h* ∉ U`. O desenho (§C, família O) cita até 48 ocorrências por par,
    mas é número de rascunho (D3), não re-derivado. Então `F* ∈ W_hi` não vale "por construção", ao contrário do que
    dizem 8.1 e 8.3.
  - Ao mesmo tempo, 8.3 afirma que `F*` está sempre em `W_lo`. O caso `W_lo = {F*}` e `W_hi = {F′}` com `F′ ≠ F*`
    (ou `W_hi = ∅`) viola `W_lo ⊆ W_hi`. Com U saturado, esse caso não é `identificado`, nem `ambiguo`, nem
    `indeterminado`.
  - O passo 3 da elevação exige inalteradas só as observações do resto do grupo ("finais das outras chaves, traços,
    replay"). Ele não exige que a observação marginal de `a` seja a mesma, então `W_lo` pode conter classes de fora
    de `W_hi`.
  - Nada diz o que acontece quando a expansão é cortada por limite de tempo ou de memória.
- **Correção.**
  1. Calcular `W_hi` sobre `U ∪ {classe(h*)}`.
  2. Definir `W_lo` como `{F*}` mais as famílias das classes **de `W_hi`** cuja testemunha se eleva, com a observação
     marginal de `a` inalterada. `W_lo ⊆ W_hi` passa a valer por definição.
  3. Declarar que qualquer corte de recurso conta como "não saturado".
  4. Acrescentar uma frase provando que os três estados formam uma partição, mais um exemplo com `h* ∉ U`
     (por exemplo, `a` com 5 candidatos).

### A02 — bloqueante — §4.6 regras 2 e 3, e §3.2 passo 3: certificados dummy de referência falsos com `Id` duplicado

- **Problema.** Com `occ = per_entity_any`, 3.2 aplica `top1` por grupo de mesmo `Id` (R30). O `rank`, porém, é
  definido por entidade, e o SPEC não diz como o `top1` escolhe dentro do grupo (ordem, desempate). As regras 2 e 3
  ignoram isso. Contraexemplos, rodados com a referência do próprio teste, no espaço CM, com `trait = v2`, limiares
  0,60 e `map = cm_gated`:
  - **`sel`:**
    - e1 (`Id` 1) com `C61` 0,90 e e1′ (`Id` 1) com `E11.9` 0,95; `occ = per_entity_any`; `sel`: `all → top1`.
    - A regra 2 certifica dummy, porque o único candidato de C61 tem `rank = 1` na sua entidade.
    - Mas o estado de C61 vai de `present` a `absent`: o `top1` do grupo `Id` 1 é `E11.9`.
  - **`occ`:**
    - A mesma evidência, com `sel = top1` e `occ`: `last_upsert → per_entity_any`.
    - A regra 3 certifica dummy, porque C61 tem um único candidato e um único `eid`.
    - O estado vai de `present` a `absent`: o grupo do `top1` muda de entidade para `Id`.
  - `Id` duplicado existe nos dados reais (4.5, R30). Um certificado falso contamina três usos:
    - a "necessidade" de 9.3, que usa a BFS com dummies de referência;
    - a poda da BFS de M;
    - qualquer geração de cenário que confie em `semantics.dummy`.
  - A regra 1 também não trata `D` com `patch:*` que altere `es` ou `cs` de candidatos de `a`. O teste devolve
    `None` nesse caso; o SPEC não diz nada.
- **Correção.**
  - **3.2:** definir o `top1` do grupo de `Id` pela ordem `(cs desc, code asc, posição asc)` sobre os candidatos de
    todas as entidades do grupo.
  - **Regra 2:** exigir que todo candidato de `a` seja o `top1` da sua entidade **e** do seu grupo de `Id`, sob os
    dois níveis de `occ` presentes no contraste.
  - **Regra 3:** exigir, além do que já pede, `sel = all` nos dois níveis ou `Id` único nas entidades dos candidatos
    de `a`.
  - **Regras 1 a 3:** devolver `None` se algum patch de `D` edita uma entidade que tem candidato de `a`.
  - Acrescentar um exemplo EX com `Id` duplicado ao JSON.

### A03 — bloqueante — §9.2: o lastro não é verificável como escrito

- **Problema.** Os passos 1 a 4 do avaliador conferem só o valor verdade e a cobertura. Três requisitos da própria
  tabela de 9.2 não são conferidos:
  - que o `S` de um certificado `eval` consta do log do `Env` **daquela** execução (método × vista × capacidade ×
    orçamento);
  - que o tipo está disponível na célula (`eval` sob R-C, `trace` fora de L2-M);
  - o que é um `trace` "derivado dos traços armazenados": não existe regra de derivação.

  Com isso, um método sob R-C pode fabricar certificados `eval` verdadeiros por adivinhação e ganhar
  `correto_sustentado`. É justamente a distinção entre sustentado e acerto por acaso (§7.4, §11.1). No teste,
  `backing_check` ignora `kind`.
- **Correção.**
  - Acrescentar um passo 0 ao avaliador. O certificado `eval` cujo `S` (traduzido e intersectado com `D`) não está
    no log e o certificado de tipo indisponível na célula são **descartados** e não contam para a cobertura.
    Registrar o motivo.
  - Definir a derivação por traço. Opções:
    - uma regra fechada: o registro único de `a` com `failed = {f}` em x0 e aprovado em x1, com os demais fatores
      certificados dummy, ⇒ `suff({f})`;
    - ou restringir `trace` a `S ∈ {∅, D}`.
  - Estender `backing_check` e EX-21 com um caso de `eval` fora do log e um caso de `trace` em L2-R.

### A04 — importante — §10.2 e §13.5: o risco seletivo é diluível por `nao_comprometido`

- **Problema.** `alternativas` com uma lista longa que contém `F*` (e `W_lo`) é pontuada `nao_comprometido` em
  `identificado`, em `incompleta` e, quando `𝒜 ⊄ W_hi`, em `ambiguo`. A saída nunca é errada, é categórica e entra no
  denominador do risco. EX-17 já tem um caso vivo (q5).
  - Um método que emite essa saída para os casos duvidosos derruba o risco sem ganhar cobertura.
  - Isso afeta a calibração a 5% (13.5) e a guarda de risco de H1b.
  - "Sempre singletons" só dá `nao_comprometido` quando `F*` é unitária; ela não é, sozinha, o vetor do problema.
  - A abstenção estratégica não aumenta a cobertura e está correta como está.
- **Correção.** Para a calibração 13.5 e para a guarda de H1b, usar o risco sobre as categóricas **comprometidas**:
  excluir `nao_comprometido` do denominador. Reportar também o risco literal de §11.1 e registrar o desvio.
  Alternativa: tratar `alternativas` com `𝒜 ⊄ W_hi` como abstenção para o risco.

### A05 — importante — §7.4 e §13.1: H1a com `b = 64` (item 1 de β)

- **Juízo.** Sim, a não inferioridade é trivial.
  - Em R-A, com vínculo e resposta completa, 8.4 dá `W = {F*}` nos dois braços. Com `b = 64 ≥ 2^|D|`, M enumera
    tudo.
  - Pior: `evaluate` devolve o traço do híbrido (11.1). Depois de ∅ e `D`, L2-R tem o mesmo que L2-M armazena, em
    **qualquer** `b ≥ 2`.
  - No núcleo determinístico, `Δa ≡ 0` por construção. O bootstrap degenera (todo `Δ* = 0`) e dá `p = 1/(B+1)`.
  - Um orçamento menor não torna H1a informativa por si. A única diferença possível viria da assimetria artificial
    de lastro: o certificado `trace` só é aceito em L2-M, embora L2-R obtenha os mesmos traços via `evaluate`.
- **Correção.**
  1. Declarar `b = 16` como primário (o regime restrito de §10.2, onde o material armazenado poderia poupar
     avaliações) e 32 e 64 como secundários.
  2. Aceitar em L2-R os certificados `trace` derivados dos traços devolvidos por `evaluate` já pagos. Sem isso, `Δa`
     mede uma regra de pontuação, não informação.
  3. Pré-declarar que um `Δ*` de variância zero é reportado como "identidade por construção" e não como evidência de
     não inferioridade. É o análogo de 13.4.
  4. Dar à parte "deve reduzir armazenamento" de H1a um critério descritivo pré-declarado: razão de bytes
     deduplicados L2-R/L2-M, com IC, e tempo de reconstrução. §2.1 do protocolo já enquadra H1a como avaliação
     operacional.

### A06 — importante — §13.1 e §10.1: estimando de H1b (item 2 de β)

- **Juízo.** Agregar dois estratos pré-declarados, com os resultados por ablação como secundários, é compatível com
  §2 e §11.3 do protocolo. A guarda de risco é adequada. Faltam quatro definições:
  1. **Denominadores dependentes da vista.** `Q_c` e `Q_ind` são calculados por vista × capacidade. Os dois braços
     pareados medem conjuntos de consultas diferentes, e a exclusão de `indeterminado` vira seleção dependente do
     braço.
  2. **Pesos dos estratos.** Não estão definidos: pelo número de consultas (estimador de razão conjunto) ou peso
     igual?
  3. **Guarda de risco.** "Limite superior de 95%" não diz se é unilateral a 95% ou o percentil 97,5.
  4. **Risco sem categóricas.** O risco não está definido quando um reamostrado não tem categóricas.
- **Correção.**
  1. Fixar o denominador comum: consultas alteradas, com família completa, e fora de `indeterminado` **nos dois
     braços**.
  2. Reportar `|Q_ind|` por braço, e uma sensibilidade que conta `indeterminado` como não coberto.
  3. Declarar o peso (recomendo o estimador de razão conjunto por consulta e cada estrato como secundário).
  4. Fixar a guarda como percentil 97,5 do bootstrap, coerente com α = 0,025, e a regra para categóricas vazias.
  5. Registrar que A1 fica fora dos estratos porque a família P é só catalogada.

### A07 — importante — §4.3 e §8: o modelo de identificação com variantes K (item 3 de β)

- **Juízo.** É uma leitura defensável de R-C ("código/ambiente parcial ou incompatível", §6.4) e segue o desenho B4,
  que ancora K nas hipóteses de F1. Três consequências precisam ser declaradas:
  1. **O efeito de L2-M sobre L2-R em R-C existe só através de K.** Em EX-11, L2-R × R-C tem evidência e vínculo e,
     ainda assim, `|W| = 2`, só porque a variante de x0 não é observável. Sem K, esse estrato de H1b tenderia a zero.
     O benchmark fixa parte do ganho que mede.
  2. **Toda execução real usa `std`.** O mundo `alt` nunca se realiza. Um método que sempre assume `std` nunca erra
     de fato, embora seja pontuado `indevidamente_exclusivo`. É coerente com §7.4, mas deixa a ambiguidade só
     hipotética.
  3. **As variantes `alt` repetem os pares de nível.** `v1` alt ≡ `v1_hyp_le_0.6`, `last_upsert` alt ≡
     `first_upsert` e `cm_gated` alt ≡ `cm_ungated`. Só o `>` dos limiares é novo. O modelo pode ser simplificado.
- **Correção.**
  - Registrar K como decisão, com a citação de F1 para cada hipótese.
  - Reportar H1b também com `K = ∅`, como sensibilidade pré-declarada.
  - Realizar a variante `alt` em parte das execuções novas da família I, para que as duas histórias ocorram.
  - Opcional: unificar as variantes e as hipóteses de divergência numa só lista.

### A08 — importante — §13.6 e §13.1: dimensionamento sem o α ajustado por Holm; p de H2 composto

- **Problema.**
  - A simulação escolhe `n` por P(limite inferior de 95% > −0,02). Sob Holm com 3 hipóteses, H1a pode ter de passar
    a α = 0,025/3.
  - O p de H2 composto (superioridade **e** não inferioridade) não está definido.
  - EX-19 usa α = 0,05 para o limite de evento zero, e o resto do SPEC usa 0,025, sem justificativa.
- **Correção.**
  - Dimensionar com o nível do pior caso de Holm (limite inferior a 1 − 0,025/3).
  - Definir `p_H2 = max(p_i, p_ii)` (teste de interseção-união).
  - Fixar o α de 13.4 e justificá-lo.

### A09 — importante — §1.2 × §1.4: `unmapped` e ausência se contradizem

- **Problema.**
  - 1.2 diz que um registro `unmapped` "não é chave nem ausência".
  - 1.4 define `ABSENT` como "a resposta existe e nenhum registro aprovado tem a chave".
  - No contraste `who_exact_fb → who_exact`, `E11.65` deixa de produzir `E11`. O texto de 1.2 sugere que
    `(med, E11)` não é ausente; 1.4 e a referência do teste dizem `absent`.
  - A família M cai nesse caso sempre.
- **Correção.** Escrever a regra explicitamente. Recomendo 1.4: a chave fica `ABSENT`. O registro `unmapped` é
  contado à parte e não gera ausência de chave própria. Acrescentar um exemplo com esse contraste.

### A10 — importante — §2 nível 3 e §5.1 do protocolo: desfechos de score, classe e granularidade não definidos

- **Problema.** O protocolo manda avaliar separadamente presença, escore, classificação e granularidade. O SPEC só
  cita "os atributos definidos para o desfecho secundário", que ele nunca define. Os botões `low_conf_thr` e
  `icd_hi` aparecem em 4.1 sem desfecho associado.
- **Correção.** Definir cada atributo (valor, igualdade, tolerância exata conforme §5.2 do protocolo) e a métrica
  descritiva correspondente, ou declarar a lacuna como desvio.

### A11 — importante — §7.2, A6 × §6.3 do protocolo: "candidatos não vencedores"

- **Problema.**
  - O protocolo remove a "materialização de candidatos não vencedores".
  - A6 remove os registros reprovados e mantém os candidatos descartados por `sel` e os membros sobrescritos pelo
    upsert. Esses também são não vencedores.
- **Correção.** A6 remove tudo o que não é o candidato vencedor de um registro aprovado: descartes de `sel`, membros
  não vencedores e registros reprovados.

### A12 — importante — §12 X(iii), e §4.1 e §0: exemplo público e valores queimados

- **Problema.**
  - X(iii), o exemplo de §7.2, é público, e a família X está na região de H1a.
  - O SPEC exclui do conjunto confirmatório o `V1_TO_V2`, mas não o X(iii).
  - O desenho §C cita 0,575 e 0,625 como níveis "test-only". P-β1 os queima, mas a proposta ainda não está
    registrada.
- **Correção.**
  - Tirar X(iii) do conjunto confirmatório, ou restringi-lo a dev/cal.
  - Registrar P-β1 em `docs/deviations.md`.

### A13 — importante — §6.3 e §9.3: completude e necessidade da BFS

- **Problema.**
  - A BFS marca "incompleta" só quando o orçamento acaba. Um `S` inadmissível pulado que não contém um admissível
    suficiente deixa a família incompleta pela definição de 6.1 (EX-13). A BFS de referência a declararia completa;
    o teste também, pois `complete = not exhausted`.
  - A "necessidade" não está definida em R-C nem sem `eval`.
  - "Dummies de referência que a vista permite: trace em L2-M" não corresponde a nenhuma regra de 4.6, que são
    todas regras de evidência.
- **Correção.**
  - Acrescentar à BFS a verificação de completude de 6.1 sobre os inadmissíveis pulados.
  - Quando a capacidade não executa `D` (R-C) ou não há `eval`, `orcamento_esgotado` é sempre desnecessário. A
    forma equivalente é definir a necessidade como 0 nessas células. **Não** usar `+∞`: pela regra de 9.3, isso
    tornaria a abstenção apropriada.
  - Tirar "trace" da frase, ou definir regras dummy por traço.

### A14 — importante — §9.3: certificado falso fora da célula `identificado`

- **Problema.**
  - O SPEC aplica "certificado falso → errado" só na linha `identificado`.
  - O `score()` do teste aplica antes de qualquer célula.
  - Para V(`F*`) em `ambiguo` com certificado falso, o SPEC dá `indevidamente_exclusivo` e o teste dá `errado`.
- **Correção.** Generalizar para todas as células, coerente com a precedência. Acrescentar um exemplo EX-S.

### A15 — importante — §7, §12 e §8: viabilidade (1.000 grupos, 8 CPUs, 15 GiB)

- **Estimativa.**
  - São cerca de 26 contrastes por grupo, portanto 26 mil contrastes, × 64 híbridos = 1,7 M execuções de grupo.
  - Com memoização por `(contraste, S, níveis usados)`, compartilhada entre vistas, isso cabe em horas com 8 CPUs.
- **Gargalos.**
  1. **Expansão de U.** A escala é símbolos^L × partições × |K| (≤ 64) × 2^|D| por consulta, e ainda mais as
     reexecuções do grupo inteiro para cada testemunha elevada.
  2. **O produto cartesiano** método × vista (≈ 15) × capacidade (3) × orçamento (3) sobre todas as consultas de
     F/M/O/X, porque a família I cruza "as mesmas execuções".
  3. **RAM compartilhada** entre sessões.
- **Correção.**
  - Memoizar U por assinatura simbólica de `a` × forma do contraste (a observação marginal é simbólica).
  - Dar um orçamento por consulta; o corte vira "não saturado" (A01).
  - Medir em dev na β3 e declarar o subconjunto de F/M/O/X cruzado na família I.
  - Criar um portão pré-P4: se a fração `indeterminado` passa de um limite declarado em algum estrato de H1b,
    revisar U antes do congelamento.

### A16 — importante — `docs/deviations.md`: desvios propostos e não registrados

- **Problema.** O registro tem só D1 a D4. Não estão registrados:
  - a cobertura só sobre alteradas (R13);
  - a família P só catalogada (R20);
  - H2 com p = 1 (P-β2);
  - L3 ≡ L2 sem execução separada;
  - os valores queimados (P-β1);
  - o piloto de anotação (P-β4);
  - o modelo K (A07).
- **Correção.** A sessão principal registra essas entradas antes de P4.

### A17 — menor — §13.3: H2 entra no Holm com p = 1 (item 5 de β) — **sem achado de mérito**

É literal ao protocolo ("três contrastes primários") e conservador: o FWER fica controlado. O custo é poder. H1a e H1b
passam a ter limiares α/3 e α/2, em vez de α/2 e α. Aceito. Uma família de 2, pré-declarada antes do teste, também
seria válida, mas exige desvio registrado. Basta o registro (A16).

### A18 — menor — R13: cobertura primária só sobre alteradas (item 4 de β) — **sem achado de mérito**

- No núcleo determinístico, os finais de x0 e x1 revelam se `a` mudou. Pôr `Q_u` no denominador inflaria a
  cobertura com casos triviais, e as falsas atribuições em `Q_u` já são medidas pelo controle nulo (§11.2 do
  protocolo).
- **Correção menor.** Escrever essa justificativa no SPEC e dizer que ela não vale na campanha: sob variabilidade,
  `Q_u` deixa de ser trivial.

### A19 — menor — `tests/test_spec_examples.py`: independência (ponto 2 da sessão principal)

- **Independência.** A referência não importa `habench`. **Dois** testes importam `habench.types.OutputState`
  (`test_output_state_vocabulary` e `test_scoring_table_is_total`), não um só como diz o status de β. Ambos usam só
  o vocabulário.
- **Detecta família mínima errada em caso não monótono?** Sim, para as expectativas do JSON:
  - EX-10 e EX-16 são não monótonos.
  - Uma BFS que presumisse monotonicidade, podando os superconjuntos de insuficientes, daria 5 avaliações e
    `{{A}}` em EX-16, e o teste falharia.
  - Uma família `{{ent_thr},{ent_thr,patch:p3}}` em EX-10 também falharia.
  - A sonda confirmou a correção da própria referência em 20.000 tabelas.
- **Limites.**
  - O teste não exercita nenhuma lógica de `habench`.
  - O cruzamento DP × ingênuo roda só nos contrastes dos exemplos.
  - A BFS é testada sem admissibilidade e sem poda por dummy.
  - Onde o SPEC é ambíguo (A02 `top1` por grupo, A09 `unmapped`), a referência escolheu uma leitura em silêncio.
- **Correção (para β3).**
  - Teste diferencial com hypothesis: `habench.oracle` × DP × ingênuo × BFS, em tabelas aleatórias com
    inadmissíveis e dummies.
  - `pipeline.core` contra o núcleo de força bruta, em evidência aleatória com `Id` duplicado e empates.

### A20 — menor — níveis de teste no SPEC (ponto 3 da sessão principal) — **sem achado**

- Nenhum valor citado como teste aparece no SPEC nem no JSON: busquei `0,575`, `0,625` e `test_only`.
- Os níveis de 4.1 são todos de dev/cal. Os valores dos exemplos (0,58, 0,59, 0,62, 0,66, 0,75) ficam queimados
  pela regra de §0.
- **Correções menores.**
  - Dizer como a lista selada é gerada e comprometida: grade, semente e hash publicado no congelamento, com o
    conteúdo guardado só na verdade.
  - Dizer que fatores categóricos não têm níveis de teste próprios; a novidade vem dos contrastes.
  - Dizer se o nível x0 de teste é o preset.

### A21 — menor — implementabilidade (itens soltos)

- **Exemplos.**
  - Em EX-05, "–" na coluna de traços quer dizer "DIAGNOSIS 0,90 padrão". Deixar isso explícito.
  - A tabela 9.3 não tem exemplo para (`ambiguo` × `orcamento_esgotado`, `contrafactual_indisponivel`, `falha`),
    (`incompleta` × `compativel_com_variabilidade`, `orcamento_esgotado`, `falha`), (`inalterado` ×
    `orcamento_esgotado`, `contrafactual_indisponivel`, `falha`), nem para os sete estados de `indeterminado` além de
    V (EX-S21). O brief pede um por célula × estado.
- **Pontuação.** `contrafactual_indisponivel` sob R-C em `ambiguo` é "desnecessária". O SPEC deve dizer ao método
  que R-C pede `informacao_insuficiente` ou `alternativas`.
- **Definições que faltam.**
  - "resposta incompleta", em `UNAVAILABLE`;
  - o comprimento do prefixo em `hier:<sha>`;
  - as células N1/N2 × capacidade;
  - a "variante real" de um nível declarado não executado (5.4);
  - a classe de `map` de 8.2 relativa à chave de `a` (categoria exata × subcategoria sob `who_cat3`).
- **Protocolo sem remissão.** O SPEC deve remeter aos documentos donos, ou declarar fora de escopo:
  - §10: B0 a B3 e a adaptação de BugDoc e Why-Diff (γ);
  - §6.5: os estados de afirmação;
  - §8.2: a base de nove combinações.
- **Controle nulo.** A referência "tudo `ausencia_de_mudanca`" da família N deve ser confirmada pelo oráculo, não
  presumida.

## 2. Resumo por pergunta do brief

| pergunta | resultado |
|---|---|
| 1. Conformidade | A10, A11, A12, A16, A21; A06 (H1b × §11.3) |
| 2. Implementabilidade | A02 (`top1` por grupo), A09, A13, A14, A21 |
| 3. Correção | exemplos conferem; BFS correta sem monotonicidade; A01 (`W_lo ⊆ W_hi`), A02 (dummy) |
| 4. Pontuação | A03 (lastro), A04 (diluição do risco), A14; tabela total confirmada |
| 5. Vazamento | A12, A20; vistas e partições sem problema no texto |
| 6. Estatística | A05, A06, A08, A17 |
| 7. Viabilidade | A15 |

## 3. Veredito

**Aprovar com correções.** As três correções bloqueantes são locais e não exigem nova auditoria completa: basta a
sessão principal reconferir as seções alteradas e o teste verde.

Correções obrigatórias:
- **Antes de β3:** A01, A02 e A03 (bloqueantes), mais A09, A13 e A14, que mudam a semântica que β3 implementa.
- **Antes do congelamento P4:** A04, A05, A06, A07, A08, A10, A11, A12, A15 e A16.

Contagem: 3 bloqueantes, 13 importantes e 5 menores.
