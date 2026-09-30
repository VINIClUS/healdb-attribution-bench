# Análise do Protocolo Experimental HealDB v0.2

Lead β, 2026-09-30. Entregável "Análise" (chunk β1). Objeto: `docs/protocolo/Protocolo_Experimental_HealDB_Revisado_v0_2.md`
(SHA-256 `7bfed6c0…a34c`). As resoluções citadas como **R01…R30** são adotadas em `docs/SPEC.md`, que usa os mesmos
identificadores.

**Convenções.**
- "§x" sem prefixo é seção do protocolo. "F1 §x", "F2 §x" e "F3 §x" são seções das fontes. "Desenho §x" é
  `docs/design/desenho_inicial.md`.
- Todo número vindo de `docs/design/*.md` é rascunho de subagente e está marcado **(a re-derivar)** (desvio D3).
- Status das citações: **confere** (a fonte diz isso na seção citada), **confere (seção)** (a fonte diz isso, mas em
  outra seção), **diverge**, **não verificável** (a fonte não diz isso, ou a fonte é externa e não foi lida).

## 0. Identidade das fontes

| Fonte | Arquivo local | SHA-256 re-derivado | Bytes | Confere com o protocolo |
|---|---|---|---|---|
| F1 | `/home/vinicius/code/HealDB/doc/PROVENIENCIA_NLP_V1.md` | `bd466b36d8b70f76119299a0be4138eccf04920f6cb7eb211ea86d31bdedd1f4` | 33.897 | sim (hash e tamanho) |
| F2 | `/home/vinicius/code/HealDB/doc/RECONSTRUCAO_V1_MATRIZ.md` | `856d5c31b7668d5807ac25fcde5942e8ed0c225a6279565b7a2f110b50ebd515` | 21.480 | sim (hash e tamanho) |
| F3 | `/home/vinicius/Downloads/Esboco_revisado_HealDB_IC_Unicamp(2).pdf` | `822750b78c0d3222da05c0a70350fad01c6fdfef34d460bd870cae2e4157a4ff` | – | o protocolo não dá hash; igual a `SHA256SUMS` |

Os nomes de arquivo de F2 e F3 diferem dos citados no protocolo (desvio D1). E1–E4 não foram lidos nesta sessão:
chamadas externas estão proibidas.

## 1. Verificação das citações

| # | Afirmação do protocolo | Fonte citada | Status | Nota |
|---|---|---|---|---|
| C01 | Mantêm-se Q1, Q2 e Q3 (§1) | F3 §2 | confere | F3 §2 define Q1–Q3. A redação do protocolo é mais estreita (Q2 fala de "conjunto de evidências" e não de "níveis de proveniência"). |
| C02 | Mantêm-se intervenções e busca de conjuntos mínimos (§1) | F3 §5 | confere | "O método buscará conjuntos mínimos de alterações … que reproduzam a mudança." |
| C03 | Mantêm-se reexecuções de referência (§1) | F3 §§2, 5 | confere | H2 e L3 em F3. |
| C04 | Mantêm-se avaliação por associação e abstenção (§1) | F3 §§3, 5–6 | confere | "atribuição de mudanças por associação" (§3); "atribuição inconclusiva" (§5); "abstenção" (§6). |
| C05 | Altera-se a definição de L2 (§1) | F3 §5 | confere | Em F3, L2 = "L1 mais traduções, respostas brutas e decisões por associação". O protocolo divide em L2-R e L2-M. |
| C06 | Altera-se a obrigatoriedade das 27 configurações (§1, §8.2) | F3 §5 | confere | "3 perfis de tradução × 3 limiares × 3 políticas de mapeamento: 27 configurações". |
| C07 | Altera-se a referência nativa (§1, §6.1) | F3 §5 | confere | Em F3, L0 é "auditoria disponível", um nível da escada. O protocolo o reinterpreta como referência nativa. |
| C08 | "A V1 conserva tradução" (§1.1) | F1 §3.3 | confere (seção) | F1 §3.3 trata do replay. A tradução armazenada está em F1 §5 (matriz) e §4.7. |
| C09 | "A V1 conserva respostas completas do ACM" (§1.1) | F1 §3.3 | confere (seção) | Está em F1 §§4.1 e 5 ("armazenada inteira, com modelo, RequestId e data HTTP"). |
| C10 | O replay reproduz `trait` e md sem diferenças (§1.1) | F1 §3.3 | confere | Tabela de F1 §3.3: 0 diferenças, ids 1..43.194 incluídos. |
| C11 | Em `entity` sobra 1 ULP sem efeito nas associações (§1.1) | F1 §3.3 | confere | Valor 2,07e-7, abaixo de 0,6: não chega a md nem a `extend`. |
| C12 | A resposta preservada inclui versão do modelo, RequestId e data HTTP (§1.1) | F1 §§4.1, 4.5 | confere | RequestId e `date` em §4.1; `ModelVersion` em §4.5. |
| C13 | "Ausência de `run_id` não equivale a ausência de proveniência por chamada" (§1.1) | F1 §§4.1, 4.5 | não verificável | F1 não usa o termo `run_id`. É inferência do protocolo, compatível com F1 §5 ("Data de execução: não há coluna; recuperável"). |
| C14 | A reconstrução do texto V1 é compatível com todos os trechos posicionados (§1.1) | F1 §4.2 | confere | 235.557 de 235.557 trechos, em 7.189 respostas. |
| C15 | A reconstrução cobre 36,95% dos caracteres (§1.1) | F1 §4.4 | confere | 2.867.811 de 7.761.312. |
| C16 | A reconstrução não prova identidade integral (§1.1) | F1 §§4.4, 8 | confere | "consistente … mas não está provada idêntica" (F1 §1). |
| C17 | V1 e V2 diferem no texto submetido (§1.1) | F1 §4.6 | confere | `ds_text_submitted` é igual ao texto V1 reconstruído em 0 de 7.447 linhas. |
| C18 | V1 e V2 diferem na versão do ACM (§1.1) | F1 §§4.5–4.6 | confere | `3.0.0.20231001` contra `3.2.0.20251001`. |
| C19 | A regra reconstruída de `extend` foi ajustada aos dados (§1.1) | F1 §2.4 | confere | "Não mostra que esse foi o código que rodou." |
| C20 | A versão 2 do depósito mantém os arquivos da versão 1 (§1.1) | F2 §1 | confere | "mantém os 4 arquivos da V1 intactos (mesmos ids e md5)". |
| C21 | O universo contém 7.447 respostas do ACM (§4.1) | F1 §4.5; F2 §4 | confere | F2 §4, linha `api_response`. |
| C22 | O universo contém 7.473 traduções (§4.1) | F1 §4.7; F2 §4 | confere | F2 §4, linha `translate_eng_leaflet_section`. |
| C23 | Esses números "não são contagens de textos independentes" (§4.1) | F1 §§4.2, 4.7; F2 §4 | não verificável | As fontes citadas não tratam de textos repetidos entre medicamentos. F1 §4.2 mostra duplicação *dentro* de um texto. A afirmação é sustentada pelo inventário do workspace: 7.044 textos EN distintos e 6.250 PT distintos (a re-derivar). |
| C24 | A mudança de representação histórica está documentada em F2 (§5.1) | F2 §6 | confere | CID-10-CM com ponto na V1; CID-10 OMS sem ponto na V2. |
| C25 | Na V1, a última ocorrência de um par pode determinar o score (§5.2) | F1 §§2.2, 6 | confere | F1 §2.2 (`vl_score`) e §6 item 1. |
| C26 | Confirmar `trait`, `entity` e md, isolar o 1 ULP, manter driver, limpeza e versões atuais (§5.3) | F1 §§3.3–3.4 | confere | A limpeza de md é ação de operador presumida (F1 §3.3). |
| C27 | 0,60 é a referência do código V1 (§8.1) | F1 §2.3 | confere | Passo 4 do funil: `vl_score ≥ 0,6 e vl_entity_score ≥ 0,6`. O limiar vale para os **dois** scores; o protocolo varia só o de entidade. |
| C28 | Why-Diff e BugDoc já estão relacionados no esboço (§10.1) | F3 §4 | confere | Referências [7] e [8] de F3. |
| C29 | Q3: 150 textos, piloto de 20, dupla anotação em 50 (§12) | F3 §5 | confere | "excluídos da avaliação final" e "130 do teste" são decisões do protocolo; F3 não diz se o piloto está dentro dos 150. |
| C30 | Cronograma compatível com 24 meses (§15) | F3 §7 | confere, com ressalva | F3: experimentos, anotação e avaliação em 13–18, método fixado no mês 15. O protocolo põe o congelamento até o mês 15 e o teste em 16–18. É compatível, mas o protocolo omite "dissertação completa até o mês 21". |
| C31 | PROV-DM descreve proveniência, não causa (§6.5) | E1 | não verificável | Fonte externa não lida. Os dados bibliográficos são iguais a F3 [11]. |
| C32 | A API documenta `ModelVersion` e não expõe seletor de versão (§9.1) | E2 | não verificável | Não lida nesta sessão. É consistente com F3 §1 e com `ambiente_e_comparadores.md` §4 (rascunho). |
| C33 | Why-Diff compara traços de proveniência de workflows (§10.1) | E3 | não verificável | Os dados bibliográficos e o DOI são iguais a F3 [7]. |
| C34 | BugDoc explora configurações para investigar falhas (§10.1) | E4 | não verificável | O DOI é igual a F3 [8]. O arXiv:2004.06530 só aparece em `ambiente_e_comparadores.md`. |
| C35 | Usar as ressalvas de F1 §§2.4, 4.4 e 8 (Referências) | F1 | confere | As três seções existem e tratam de limites. |
| C36 | Em F2, a igualdade dos SQLs remove só a linha `-- Dump completed on` (Referências) | F2 §§1, 8 | confere | Também não implica igualdade bruta dos compactados: os `.rar` e `.zip` têm md5 distintos (F2 §2). |
| C37 | F3 tem três páginas e é de Vinícius André de Santana (Referências) | F3 | confere | pdftotext: 3 páginas. |
| C38 | Hashes e tamanhos de F1 e F2 (Identificação) | – | confere | Re-derivados (seção 0). |

**Síntese.**
- Nenhuma citação diverge em conteúdo.
- Duas citam a seção errada (C08, C09).
- Uma se apoia em fonte que não a sustenta (C23). A afirmação é verdadeira, mas a evidência está no inventário do
  workspace, não em F1/F2. A versão confirmatória deve citar o manifesto de grupos do repositório.
- C13 é inferência do protocolo apresentada junto de uma citação.
- E1–E4 ficam não verificáveis nesta fase.

## 2. Consistência interna

| # | Ponto | Verificação | Resultado |
|---|---|---|---|
| I01 | Orçamento de tradução (§13) | 150 × 3 × 5 = 2.250; 60 × 3 × 10 = 1.800 | confere |
| I02 | Orçamento do ACM (§13) | O protocolo não totaliza. Piloto: bloco isolado 60 × 10 = 600, mais 1.800 propagações = **2.400 chamadas-base**, mais o smoke test (20 × 5 = 100, decisão do usuário e brief δ). Custo por chamada: `max(1, ⌈chars/100⌉) × US$0,0005` (preço a re-derivar). Um texto mediano (~380 caracteres com cabeçalho) custa ~US$0,002, e o máximo (10.000 caracteres) US$0,05. O pior caso de 2.500 chamadas é US$125, acima do teto de US$30; o caso típico fica em poucos dólares. | Viável se o comprimento dos textos do piloto for controlado. O teto do ledger é a trava efetiva. A tradução (Bedrock) não tem preço fixado. |
| I03 | Papéis das realizações (§9.2) | Piloto 6 + 4 = 10; teste 3 + 2 = 5 | confere |
| I04 | "Cinco totais significa referência mais quatro adicionais" (§9.2) | O singular "referência" colide com "três referências e duas realizações de avaliação". | Redação ambígua. Resolução em **R23**. |
| I05 | Campanha de teste (§9.2, §11.3, §12) | `docs/decisoes.md`: a campanha 150 × 5 não está autorizada. | O terceiro contraste primário (H2) não é executável confirmatoriamente nesta fase. §12 ("preferencialmente no subconjunto prospectivo de 150") também depende dela. Resoluções em **R15** e **R18**. |
| I06 | Partições (§4.3) | 200 + 200 + 600 = 1.000 | confere. O dev passa de 200 (D4), então o total pode passar de 1.000. |
| I07 | Anotação (§12) | 20 + 130 = 150; 50 + 80 = 130 | confere. A partição de origem dos 20 do piloto não é dita (**R24**). |
| I08 | Redação de H1a (§2) | Compara "perfil reduzido" com "materialização completa" (L2-R × L2-M), no replay validado (§11.3: R-A). | O regime de orçamento não é dito. Com orçamento suficiente, os dois perfis enumeram tudo e a não inferioridade é quase automática (**R09**). "Deve reduzir armazenamento" não diz se é parte testada da hipótese; o SPEC trata como desfecho descritivo. |
| I09 | Redação de H1b (§2) | "a risco comparável" não é definido. "Medido separadamente para cada ablação" colide com um contraste primário único em §11.3. | **R17** |
| I10 | Redação de H2 (§2) | É composta: redução de falsas atribuições e não inferioridade de cobertura (2 pp). | Dois testes num mesmo contraste primário (**R18**). |
| I11 | Continuidade com F3 | O H1 de F3 era L2 × L1. O protocolo não tem L1 × L2 entre os contrastes primários. | Coerente com §1 ("alteram-se"). L1 × L2 fica como comparação secundária. |
| I12 | Incerteza (§11.3 × F3 §6) | F3 reamostra "por texto"; o protocolo, por grupo documental. | O protocolo é mais estrito. Coerente. |
| I13 | Terminologia (§7.2 × §7.4) | §7.2 chama `{limiar}` e `{candidato}` de duas "explicações mínimas" da mesma família. §7.4 usa "família de explicações alternativas" para ambiguidade entre histórias. | Colisão de termos (**R01**). |
| I14 | Fatores binários (§7.3 × §8.1) | A grade 0,55 / 0,60 / 0,65 tem três níveis, mas cada contraste usa dois. "Nove combinações locais" (§8.2) = 3 limiares × 3 mapeamentos. | confere |
| I15 | Curvas 16/32/64 (§10.2 × §7.3) | 64 = 2⁶ é a enumeração completa só se ∅ e D contarem como avaliações. | **R08** |
| I16 | "Hashes" em L1 (§6.2) | Não diz de quais artefatos. Hashes de respostas revelam se o ACM mudou. | **R04** |
| I17 | R-A × R-B (§6.4) | Sem fator de preparação ou de ACM em D, R-B equivale a R-A. | Células equivalentes, não "não aplicáveis" (**R22**). |
| I18 | Alvo de risco (§2, §11.1) | 5% nos dois lugares | confere |
| I19 | Unidade (§4.2 × §11.2) | Resultado por (grupo, contraste, associação); controle nulo por grupo | confere |
| I20 | Multiplicidade (§11.3) | "Procedimento fixado antes do teste", sem nomeá-lo | Holm (**R15**) |
| I21 | §1.2 × números | Todos os números são propostas | confere. Nada no protocolo é apresentado como resultado. |

## 3. Lacunas operacionais e resolução adotada no SPEC

Cada resolução é uma decisão de especificação, revisável na GATE 2. As marcadas **[revisar]** também estão em
"Perguntas" no status.

| ID | Lacuna | Resolução adotada (resumo; a definição completa está no SPEC) |
|---|---|---|
| R01 | "Explicação mínima" × "explicações alternativas" (I13) | Uma **família** é a anticadeia de todos os conjuntos mínimos suficientes de uma história. `explicacao_verificada` afirma **uma** família, que pode ter vários conjuntos: o exemplo de §7.2 é verificado com família `{{limiar},{candidato}}`. `alternativas` afirma **duas ou mais famílias candidatas**, das quais a verdadeira é uma. |
| R02 | Espaço de comparação | É declarado por contraste. O padrão é CID-10 OMS (`decisoes.md`); saídas CM são projetadas por exata+fallback e rotuladas "projeção estrutural". Contrastes do bundle `EXTEND` usam o espaço CM, porque no espaço OMS `map` e `EXTEND` não têm efeito. |
| R03 | Falha como ausência | Uma associação cujo medicamento está `UNAVAILABLE` em x0 ou x1 não é elegível. Entra no fluxo de elegibilidade e nunca vira "desaparecimento". |
| R04 | Hashes em L1 | L1 contém o SHA-256 de cada artefato da execução (texto submetido, tradução, resposta, saída), sem os corpos. |
| R05 | O diff declarado não reproduz x1 | A verdade usa sempre as configurações **executadas**. O broker replica com as executadas só se a vista tem o vínculo ao código executado; senão, com as declaradas. Validar o replay é tarefa do método. Se o próprio diff executado não reproduz x1 no núcleo, o contraste é inválido, sai do benchmark e fica registrado. |
| R06 | Suficiência não monótona | Minimalidade por inclusão entre subconjuntos admissíveis, sem supor monotonicidade. O oráculo marca `nonmonotone`. |
| R07 | Subconjuntos inadmissíveis | A família é relativa aos subconjuntos admissíveis. Ela é **completa** se todo S inadmissível contém propriamente algum admissível suficiente. Família incompleta → a referência é `contrafactual_indisponivel`. |
| R08 | Unidade de orçamento | Uma avaliação = um run híbrido do grupo documental inteiro para um S distinto. ∅ e D contam. Repetir S não custa. Ler os finais observados não conta. |
| R09 | Regime de orçamento de H1a **[revisar]** | Primário: regime suficiente, 2^|D| avaliações por contraste (64 com |D| = 6). Secundários: curvas de 16 e 32. Armazenamento e tempo entram como desfechos descritivos de custo. |
| R10 | Referência de identificação | Universo finito declarado U. W_lo ⊆ W_hi, saturação e status `identificado`, `ambiguo` ou `indeterminado`. U só é preciso quando a observação não determina a tabela-verdade. |
| R11 | Pontuação de alternativas e casos de sobreposição | A tabela de pontuação é uma partição total. Precedência: errado > indevidamente exclusivo > não comprometido > correto sustentado. |
| R12 | Lastro de `explicacao_verificada` | Certificados verificados pelo avaliador: afirmação falsa → errado; cobertura insuficiente → indevidamente exclusivo. |
| R13 | Denominadores | A cobertura primária usa as consultas **alteradas** elegíveis, fora `indeterminado` e as de família incompleta. O risco seletivo usa as categóricas dessas consultas mais as de família incompleta. Consultas inalteradas alimentam as métricas de controle nulo. `falha_de_execucao` fica no denominador como não coberta. |
| R14 | Peso por caso × por grupo | O primário é o estimador de razão agregado por consulta, com inferência por grupo. A média por grupo é secundária. |
| R15 | Multiplicidade | Holm sobre os 3 contrastes primários, α unilateral 0,025 por família. Um contraste não executado entra com p = 1. |
| R16 | Teste de não inferioridade | Bootstrap pareado por grupo, B = 2.000, semente fixa. Rejeita H0: Δ ≤ −0,02 se o percentil 2,5% de Δ* passa de −0,02. p = (1 + #{Δ* ≤ −0,02}) / (B + 1). |
| R17 | Estimando de H1b **[revisar]** | Diferença de cobertura "com evidência efetiva − sem ela", agregada sobre os cenários I pré-declarados. Divergência: L2-R × (L2-R − A3) em R-A. Perda de replay: L2-M × L2-R em R-C. Teste de superioridade, com a guarda "risco(com) − risco(sem) ≤ +2 pp" no limite superior. Resultados por ablação ficam secundários. |
| R18 | Estimando de H2 | Composto: superioridade na taxa de falsas atribuições **e** não inferioridade de cobertura a −2 pp, L3 × L2 com o mesmo método. Sem campanha de teste, o contraste não é executado: p = 1 no Holm, e o piloto dev/cal é exploratório. |
| R19 | Mapeamento N1/N2 | Emulação das políticas V1 e V2 sobre as mesmas execuções: artefatos no esquema histórico, sem vínculo ao código executado, capacidade de replay restrita aos parâmetros que o código histórico expõe. |
| R20 | Família P sem chamadas novas | Só catalogada. A referência de qualquer instância é `contrafactual_indisponivel`. Nenhuma instância entra nos denominadores desta fase. |
| R21 | Bundles | Um bundle declarado conta como **um** fator binário. A mesma mudança em duas granularidades dá famílias diferentes, ambas corretas cada uma na sua granularidade. |
| R22 | Células n/a × equivalentes | n/a estrutural: L1 × {R-A, R-B}, e A2 × R-A para replay pleno. Equivalente: R-B ≡ R-A quando D não tem fator de preparação ou de ACM; não é rodado em separado. |
| R23 | Papéis das realizações (I04) | O par-alvo usa realizações de **avaliação**. As referências (6 no piloto, 3 no teste) são as "referências adicionais" e só L3 as vê. "Cinco totais" conta todas as realizações por texto e perfil. |
| R24 | Piloto de anotação | Os 20 do piloto saem de dev/cal. Proposta para o lead δ; fora do SPEC. |
| R25 | Fatores de evidência | Um patch semissintético é um fator `patch:<id>` de estágio `acm`. Não aparece na configuração declarada. No `Env`, cada um aparece como identificador opaco. |
| R26 | `compativel_com_variabilidade` no núcleo determinístico | Numa consulta alterada é errado. Numa inalterada é não comprometido. Só pode ser correto em cenários do simulador declarado ou da campanha. |
| R27 | Eventos zero | Limite exato unilateral de Clopper–Pearson no nível de grupo; com 0 eventos em n grupos, 1 − α^{1/n}. |
| R28 | Níveis de teste | Sorteados no congelamento de uma lista selada, que exclui todo valor citado no SPEC ou em `docs/design/`. Esses valores contam como "queimados". |
| R29 | Replay sob ablação | O broker replica sobre a evidência que o perfil preserva. Com A2 (só top-1), o replay é degradado e pode não validar. |
| R30 | Duplicata de `Id` em respostas | Na semântica `per_entity_any`, entidades com o mesmo `Id` na mesma resposta se fundem, como no upsert da V2 (a re-derivar: 71 respostas V2). |

## 4. Achados empíricos preliminares que mudam o desenho (a re-derivar)

Todos vêm de computações de rascunho de subagentes (`docs/design/*.md`). Nenhum entra em relatório sem re-derivação em
código versionado (lead α, `historical/`).

| # | Achado (a re-derivar) | Consequência para o desenho |
|---|---|---|
| E01 | O ACM é repetível dentro de uma execução: 0 de 1.554 pares diferem na V1 (197 grupos de texto EN idêntico) e 0 de 1.937 na V2 (319 grupos). Limites superiores unilaterais de 95% ≈ 1,5% e 0,9% dos grupos. | H2/L3 não pode ser exercido com dados históricos. Só a campanha (Estudo C) ou um simulador declarado (apenas teste de mecanismo, §9.5) o fazem. H2 provavelmente sai inconclusiva (§2.1). |
| E02 | No espaço CID-10 OMS, `map` não tem efeito: o portão de hierarquia da V1 e o descarte `NO_MAP` da V2 são o mesmo predicado. Participação de `map` em conjuntos mínimos do contraste real: 0. | O bundle `V1_TO_V2` tem 5 fatores efetivos. `map` serve de fator nulo natural (família N-b). `EXTEND` só tem efeito no espaço CM (R02). |
| E03 | Só `extend_amostra.csv` já cobre ~278 medicamentos. | dev > 200 (D4). |
| E04 | Nenhum score é exatamente 0,60. | Casos de borda exigem patches sinalizados, ou seja, casos semissintéticos, estratificados por origem. |
| E05 | Listas de conceitos com 0 ou 5 itens, em ordem decrescente e sem empate no topo. | Invariantes que todo patch deve preservar. O desempate de `sel` por código quase nunca é acionado. |
| E06 | No contraste real, ~10% das associações alteradas são não monótonas. Formas: ~61% com 1 conjunto, 31% com 2, 8% com 3, <1% com 4–5 (sobre o corpus inteiro, D2). | Busca e oráculo têm de ser corretos sem monotonicidade (R06). As cotas de forma vêm de dev/cal, não desses números. |
| E07 | 804 tabelas-verdade distintas em 141.662 associações (5 fatores efetivos). Só com evidência de extremos, 45 famílias coocorrem. | L1 é genuinamente ambíguo. Um universo de classes (não de histórias) é tratável. A adequação do universo é conferida só em dev/cal. |
| E08 | Uma função Python parametrizada reproduz V1 (`entity`, `trait`, md) e V2 (`entity_icd`, `entity_trait`, `cutoff_audit`, presença em md) com 0 diferenças. | R-A é viável para os fatores pós-ACM. A GATE 1 (lead α) confirma. |
| E09 | 7.136 pares (EN, PT) distintos contra 6.250 PT distintos: textos PT idênticos receberam traduções EN diferentes. | Há variabilidade histórica da tradução (ou retradução). Isso motiva o bloco "tradução isolada" (§9.1), mas não é teste causal (Q1 descritivo). |
| E10 | Agrupar por EN idêntico economiza só 5,4% das chamadas; 197 grupos EN têm mais de um medicamento. | Pouca repetição natural. Os nulos "c" (repetição real) são escassos. |
| E11 | 6,2% dos scores de entidade e 12,6% dos de conceito caem em [0,55; 0,65). | A família F tem casos naturais suficientes perto dos limiares da grade de calibração. |
| E12 | A ordem do array difere da ordem de `Id` em toda resposta não vazia; 71 respostas V2 repetem um `Id`. | `occ` depende da ordem do array, que nunca é reordenada (§5.2). A política de `Id` repetido é R30. |
| E13 | 1.460 entidades `TIME_TO_DX_NAME` não têm conceitos. | O filtro DX_NAME da V2 não tem efeito e não entra como fator. |
| E14 | O SQL commitado da V2 difere do executado (bug do backspace; F1 §4.6, verificado na fonte). | É uma divergência real declarado × executado, mas no estágio de preparação. Fica na família P (catalogada) e em Q1, não no núcleo local. |
| E15 | A documentação da regra HYPOTHETICAL (aceita se ≤ 0,6) difere do código (veta se > 0,65); verificado em F1 §6 item 2. | É a variante natural de divergência para a família I (EX-11 no SPEC). |
| E16 | BugDoc: só `StackedShortcutStandalone` roda em processo, e a semântica é "definitiva", não a suficiência no contexto x0. Why-Diff: não há código público. | §10.1: adaptação fiel de BugDoc com a ressalva documentada. Para Why-Diff, registrar a limitação e restringir alegações. |
| E17 | Só 36,95% do texto V1 está verificado (F1 §4.4, verificado na fonte). | Fatores de preparação da V1 são inferidos (`inferido_compativel`), não armazenados. |

## 5. Ameaças à validade

**Construto**
- **Granularidade dos fatores.** Famílias mínimas dependem dela (§7.2). Um bundle e seus componentes dão famílias
  diferentes (R21). Os resultados só valem para o catálogo congelado.
- **Casos semissintéticos.** Patches de resposta do ACM não representam o comportamento real do serviço. Toda métrica é
  estratificada por origem (real × semissintético); nenhuma conclusão sobre o ACM real vem de casos editados.
- **Identificação relativa a U.** A ausência de testemunha em U não prova identificação global (§7.4). Casos
  `indeterminado` saem dos denominadores primários, o que pode favorecer métodos que só acertam casos fáceis. A
  proporção excluída é reportada por perfil.
- **Referência histórica.** V1→V2 mistura texto, versão do ACM e pós-processamento, e não serve de referência causal por
  associação (§2, Q1). No núcleo, o contraste real `V1_TO_V2` roda sobre as respostas V1 fixadas e só mede o
  pós-processamento.

**Interna**
- **Exposição do corpus inteiro no planejamento (D2).** Formas de família e repetibilidade foram vistas em grupos que
  serão de teste. Mitigação: cotas e calibração só em dev/cal; `V1_TO_V2` fora do conjunto confirmatório nos grupos de
  teste.
- **Vazamento de níveis de teste.** O desenho inicial nomeia candidatos a níveis de teste. Proposta: considerá-los
  queimados e excluí-los da lista selada (R28, desvio proposto P-β1).
- **Mesma origem de modelo.** Oráculo, método e SPEC saem de sessões do mesmo fornecedor de modelos. Mitigação:
  referência ingênua independente dentro dos testes (sem importar `habench`), auditoria T22 e revisão humana na GATE 2.
- **Isolamento.** Um método que lê a verdade por caminho alternativo invalida tudo. Mitigação: testes de isolamento,
  identificadores HMAC e testes canário (§14).

**Estatística**
- **Diluição.** Com orçamento suficiente, L2-R e L2-M chegam ao oráculo e a não inferioridade de H1a sai quase
  automática (R09). O relatório deve mostrar as curvas de 16 e 32.
- **Poucos grupos por forma rara.** Formas com 4–5 conjuntos têm n pequeno. Reportar sem inferência.
- **Cota 25 + 25 por contraste.** Muda a prevalência natural: casos de estresse não estimam prevalência (§4.4). As
  probabilidades de inclusão são registradas.
- **H2 sem variabilidade (E01).** Limite de detecção a reportar (§9.5).

**Externa**
- Um pipeline, uma versão do ACM por execução, um espaço de comparação principal (OMS) e textos em inglês traduzidos.
  As conclusões ficam restritas ao HealDB (§16).

**Medição de custo**
- Tempo de CPU e RSS têm ruído de máquina compartilhada (15 GiB para várias sessões). Reportar medianas de repetições e
  o custo amortizado com a regra declarada.

## 6. Emendas propostas para a versão confirmatória

1. Citar a seção correta em §1.1 (C08, C09) e trocar a fonte de C23 pelo manifesto de grupos do repositório
   (`repro/corpus_groups.csv`).
2. Adotar a terminologia de R01 em §7.2 e §7.4: "família de conjuntos mínimos" × "famílias alternativas".
3. Fixar em §11.3 o regime de orçamento do contraste H1a (R09), o estimando de H1b com sua guarda de risco (R17) e o
   estimando composto de H2 (R18).
4. Nomear Holm, α unilateral 0,025 e p = 1 para contraste não executado (R15).
5. Declarar H2 confirmatória condicionada à autorização da campanha de teste. Sem ela, H2 é exploratória no piloto
   dev/cal (I05).
6. Reescrever §9.2 sem "referência mais quatro adicionais": "cinco realizações por texto e perfil: três de referência,
   visíveis só em L3, e duas de avaliação, que formam o par-alvo" (R23).
7. Dizer em §12 de onde vêm os 20 textos do piloto de anotação (dev/cal) e o que acontece sem a campanha de teste:
   amostrar os 130 entre os grupos de teste após a abertura.
8. Dizer em §6.2 de quais artefatos L1 guarda hash (R04).
9. Registrar em §4.3 o tamanho efetivo do dev (> 200, D4).
10. Incluir em §8 o espaço de comparação por contraste (R02) e a nota de que `map` não tem efeito no espaço OMS (E02).
11. Declarar em §14 a lista de níveis queimados (R28).
12. Acrescentar em §11.1 a regra de denominadores (R13) e o tratamento de `falha_de_execucao`.
