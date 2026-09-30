# Protocolo experimental revisado — HealDB

## Atribuição de mudanças sob proveniência parcial e reexecução limitada

**Versão:** 0.2, proposta para discussão e posterior pré-registro.  
**Base documental:** esboço de pesquisa do IC/Unicamp e levantamentos de reconstrução/proveniência de 29/09/2026.  
**Estado:** desenho experimental; não representa experimento executado, hipóteses confirmadas ou protocolo já registrado.  
**Escopo:** pipeline de associações medicamento–doença do HealDB, sem dados de pacientes.

## 1. Objetivo e relação com o esboço

Desenvolver e avaliar um método que determine quais explicações de uma mudança por associação são sustentadas pelas evidências disponíveis, quais dependem de reexecução e quando não existe evidência suficiente para uma conclusão única. Medir correção, cobertura, abstenção e custo, sem pressupor que materializar todos os intermediários seja necessário ou que diferenças históricas demonstrem não determinismo.

Mantêm-se as três perguntas do esboço: Q1, caracterização de mudanças; Q2, suficiência e custo da proveniência para atribuição; Q3, efeitos sobre o suporte documental das associações. Mantêm-se também as intervenções, a busca de conjuntos mínimos, as reexecuções de referência, a avaliação por associação e a possibilidade de abstenção. Alteram-se a referência nativa, a definição de L2, a relação entre história e teste causal e a obrigatoriedade do produto de 27 configurações. [F3, §§2, 5–6]

### 1.1 Premissas documentadas, não resultados desta proposta

- A V1 conserva tradução e respostas completas do ACM. O replay relatado reproduz `trait` e `hd_medication_disease` sem diferenças; em `entity`, sobra uma diferença de 1 ULP sem efeito nas associações. Essas constatações exigem confirmação pelo pacote de reprodução antes do congelamento do experimento. [F1, §3.3]
- A resposta preservada inclui versão do modelo, RequestId e data HTTP. Ausência de `run_id` não equivale a ausência de proveniência por chamada. [F1, §§4.1, 4.5]
- A reconstrução do texto V1 é compatível com todos os trechos posicionados verificados, mas cobre somente 36,95% dos caracteres. Não prova identidade integral. [F1, §§4.2–4.4]
- V1 e V2 diferem no texto submetido e na versão do ACM. Sua comparação não isola variabilidade sob condições fixas. [F1, §§4.5–4.6]
- A regra reconstruída de `extend` foi ajustada aos dados; reproduzir essa tabela não identifica o programa original. [F1, §2.4]
- A versão 2 do depósito mantém os arquivos da versão 1. Há preservação de snapshots, ainda que não se conheça toda a história de execução. [F2, §1]

Os relatórios são evidência preliminar fornecida pelo pesquisador. Este protocolo não afirma que seus scripts, dumps ou logs foram reexecutados na elaboração do plano.

### 1.2 Decisões novas de planejamento

Todos os números de amostra, margens, orçamentos e critérios operacionais abaixo são propostas deste protocolo. Eles não são resultados dos relatórios nem exigências institucionais. A versão confirmatória fixará seus valores após desenvolvimento e calibração, antes da abertura do teste.

## 2. Perguntas, hipóteses e desfechos

### Q1 — Mudanças e recuperabilidade

Quais diferenças aparecem nos dados históricos e nas execuções prospectivas? Quais artefatos estão armazenados, quais podem ser rederivados, quais são somente inferíveis e quais permanecem desconhecidos nos materiais examinados?

A investigação histórica é descritiva. Não se usará V1→V2 como referência causal por associação, salvo em contrastes locais cuja intervenção tenha sido efetivamente executada e verificada, com escopo declarado.

### Q2 — Atribuição, informação e custo

Qual conjunto de evidências permite sustentar explicações corretas, com que cobertura e a que custo, sob diferentes capacidades de reexecução?

**H1a — Preservação reduzida com replay verificável.** Quando as entradas das etapas determinísticas, as saídas externas e os artefatos necessários ao replay estão preservados, o perfil reduzido rederivável não perde mais que uma margem pré-especificada de cobertura correta em relação à materialização completa. Deve reduzir armazenamento; pode aumentar o tempo de reconstrução.

**H1b — Valor da evidência efetiva de execução.** Em cenários com divergência entre configuração declarada e execução, ou com perda de capacidade de replay, preservar entrada efetivamente enviada, código efetivamente executado e/ou intermediários pertinentes aumenta a cobertura de explicações sustentadas a risco comparável. O efeito será medido separadamente para cada ablação; não se pressupõe ganho em todos os casos.

**H2 — Reexecuções de referência.** Quando houver variabilidade residual relevante sob condições observáveis fixadas, acrescentar referências independentes reduz falsas atribuições a alterações deliberadas, sem queda de cobertura superior à margem fixada. A conclusão será condicionada ao componente, perfil e janela observados.

Para H1a e H2, a margem inicial de planejamento é **2 pontos percentuais** de cobertura. Para comparação de cobertura a risco controlado, o alvo inicial é **5% de risco seletivo**. São escolhas operacionais a justificar antes do teste; não derivam dos dados históricos. Não se alterará a margem para acomodar um resultado de teste.

### Q3 — Qualidade das associações

Como as mudanças explicadas se relacionam ao suporte documental, precisão e revocação das associações? A referência é a bula, não eficácia terapêutica. Estabilidade e correção serão avaliadas separadamente. [F3, §6]

### 2.1 O que refutaria ou limitaria as hipóteses

H1a é uma avaliação operacional da implementação e dos custos sob pressupostos verificáveis, não uma alegação de novidade por afirmar que o mesmo cálculo determinístico produz o mesmo resultado. H1a não será sustentada se o intervalo de incerteza não permitir excluir uma perda maior que a margem, ou se o replay não satisfizer suas condições. H1b poderá mostrar ganho apenas operacional ou em algumas famílias. H2 ficará inconclusiva, ou sem evidência de benefício nas condições examinadas, quando houver pouca variabilidade, poucas unidades independentes ou ausência de ganho a cobertura comparável. Nenhum resultado exige confirmar as três hipóteses para que o estudo produza informação útil.

## 3. Três estudos separados

| Estudo | Material | Finalidade | O que não demonstra |
|---|---|---|---|
| A — Reconstrução histórica | V1/V2, respostas preservadas, código e documentação históricos | Caracterizar preservação, diferenças e limites de reconstrução | Causa única da transição histórica ou não determinismo |
| B — Benchmark controlado | Respostas reais fixadas, cenários locais e casos semissintéticos rotulados | Avaliar atribuição, conjuntos mínimos, suficiência e abstenção | Comportamento estocástico real do serviço a partir de um simulador |
| C — Execução prospectiva | Chamadas novas, registros completos e intervenções controladas | Medir variabilidade, efeitos médios e suporte documental | Recuperar versões históricas do serviço ou provar causa de uma realização isolada |

Os achados históricos conhecidos servem para desenvolvimento e desenho de famílias de cenários. Não serão reembalados como descobertas inéditas do teste.

## 4. Corpus, unidades e separação de dados

### 4.1 Universo e inclusão

Usar os artefatos abertos descritos em F1/F2. O universo relatado contém 7.447 respostas do ACM e 7.473 traduções, mas esses números não são contagens de textos independentes. [F1, §§4.2, 4.7; F2, §4]

Construir um inventário por medicamento, registro ANVISA quando disponível, documento-fonte, texto em português, tradução, resposta e snapshot. Identificadores internos não serão presumidos estáveis entre versões. Uma correspondência histórica somente será aceita se justificada pelas tabelas e metadados; correspondências ambíguas permanecerão explícitas.

Respostas vazias, textos longos, falhas e entradas ausentes não serão eliminados silenciosamente. Formarão estratos próprios ou terão exclusão justificada em um fluxo de elegibilidade.

### 4.2 Unidade experimental

A unidade de resultado é `(grupo documental, contraste de execuções, associação)`. A unidade de amostragem e inferência estatística é o **grupo documental**, não cada linha de associação.

Agrupar documentos idênticos ou quase duplicados, versões do mesmo texto e medicamentos que compartilham bula. A regra de agrupamento será definida sem consultar o resultado de teste. Registrar quantos documentos, medicamentos e associações cada grupo reúne.

### 4.3 Tamanho inicial e partições

Meta de planejamento: cerca de **1.000 textos distintos**, preservando os grupos inteiros:

- aproximadamente 200 para desenvolvimento;
- aproximadamente 200 para calibração;
- aproximadamente 600 para teste bloqueado.

Esses totais poderão variar para não romper grupos. Se não houver 1.000 textos elegíveis suficientemente distintos, não completar com duplicatas. Publicar o tamanho efetivo e reajustar o protocolo antes do teste.

Bulas inspecionadas individualmente na reconstrução, incluindo a amostra de `extend`, pertencem ao desenvolvimento. Se isso consumir mais que a meta de 200, ampliar essa partição e registrar a alteração. O fato de o corpus histórico já ser conhecido será declarado como limitação; a novidade de teste estará também nos contrastes e execuções prospectivas não usados no ajuste.

### 4.4 Estratificação

Considerar comprimento, categorias terapêuticas disponíveis, presença/ausência de entidades, ocorrência de traits, multiplicidade de candidatos, proximidade dos limiares e necessidade de fallback. A avaliação populacional e a avaliação de estresse serão separadas. Casos deliberadamente escolhidos por produzir uma mudança não estimam a prevalência natural dessas mudanças.

O tamanho final será escolhido por simulação de precisão usando desenvolvimento/calibração e dependência por grupo, não pela suposição de que milhares de associações equivalem a milhares de observações independentes. Se o orçamento não permitir precisão suficiente para a margem de 2 pontos percentuais, reportar o estudo como estimativo, sem reivindicar não inferioridade.

## 5. Saídas comparáveis e fidelidade do replay

### 5.1 Representação das associações

A chave inclui medicamento reconciliado, **sistema de codificação, versão da terminologia e código**. CID-10-CM e CID-10/OMS não serão tratados como a mesma terminologia por remoção de pontos ou truncamento. A mudança de representação histórica está documentada em F2. [F2, §6]

Na parte confirmatória prospectiva, fixar uma terminologia de saída e um schema. Comparações históricas por prefixo serão descritas como projeções estruturais. Generalização/especialização requer relação ancestral válida na hierarquia escolhida; um prefixo comum não basta para afirmar equivalência clínica.

Avaliar separadamente presença/ausência, escore, classificação e mudança de granularidade. Falha de execução não será representada como ausência de doença.

### 5.2 Três níveis de igualdade

1. **Arquivo bruto:** bytes exatos, incluindo metadados. Manter SHA-256 e o arquivo original.
2. **Conteúdo de extração:** remover somente uma lista pré-fixada de metadados de transporte, conservando versão do modelo, entidades, traits, candidatos, escores e informações relevantes de ordem.
3. **Decisão:** conjunto de associações e atributos definidos para o desfecho.

A serialização para comparação nunca substituirá a entrada do pipeline. Na V1, a última ocorrência de um par pode determinar o score; ordenar arrays pode alterar o comportamento que se tenta reproduzir. [F1, §§2.2, 6]

Diferenças numéricas serão inicialmente registradas exatamente. Tolerâncias de arredondamento poderão ser usadas em análises auxiliares, nunca para ocultar cruzamento de limiar ou declarar identidade binária.

### 5.3 Referência histórica reproduzida

Arquivar commit completo, blobs, dump bruto e normalização explicitada. Confirmar `trait`, `entity` e md com comparação exata, e isolar a discrepância de 1 ULP. Manter driver, limpeza de tabelas, versões atuais usadas e ações presumidas como parte do replay, sem apresentá-las como recuperação do ambiente original. [F1, §§3.3–3.4]

Separar código histórico, adaptações de execução e patches inferidos. `extend` permanece caso de reconstrução, não referência do programa histórico verdadeiro.

## 6. Proveniência: referência nativa e perfis experimentais

### 6.1 L0 é uma referência nativa, não o degrau inferior de uma escada

**L0-V1** e **L0-V2** incluem tudo o que os respectivos pacotes, código histórico e documentação efetivamente oferecem. A referência poderá rederivar resultados, ler metadados de chamadas e executar o mesmo procedimento de busca que for compatível com suas evidências.

A análise histórica de L0 é descritiva. Para comparação controlada, produzir **emulações das políticas de preservação V1/V2** sobre as mesmas novas execuções. Chamar essas vistas de `N1` e `N2`, não de novos dados históricos.

O relatório de reconstrução não será fornecido ao método como resposta pronta de um teste histórico. Inferências produzidas por esse relatório serão tratadas como conhecimento de desenvolvimento.

### 6.2 Perfis controlados

| Perfil | Informação visível | Capacidade esperada |
|---|---|---|
| L1 | Fonte, resultado final, hashes e configurações declaradas: prompts, parâmetros, commit, limiares e mapeamentos | Detectar diferenças declaradas; não observar corpos de chamadas nem intermediários adicionais |
| L2-R — reduzido rederivável | L1 + traduções, requisições efetivas, respostas externas completas, vínculo com código efetivamente executado, ambiente/terminologia/estado necessários ao replay | Rederivar etapas determinísticas quando suas condições forem satisfeitas |
| L2-M — materializado | L2-R + candidatos, traits, decisões, descartes e associações materializados por execução | Evitar parte da recomputação e conservar evidências adicionais quando replay falha |
| L3-R / L3-M | Respectivo L2 + reexecuções independentes de referência | Estimar variabilidade residual e calibrar decisões/abstenção |

O sufixo R não significa que o replay sempre funcionará: sua disponibilidade será um fator separado. L2-R é um perfil proposto, não uma alegação de conjunto mínimo universal.

### 6.3 Ablações dirigidas

Partindo de L2-R/L2-M, remover isoladamente: texto efetivamente submetido; resposta bruta mantendo apenas top-1; vínculo ao código realmente executado; versões de ambiente; ações operacionais relevantes; materialização de candidatos não vencedores. Depois avaliar um conjunto pequeno de perdas combinadas, definido antes do teste.

O avaliador preserva a verdade completa. O método recebe apenas a vista e as capacidades autorizadas. Proibir recuperação dos artefatos ocultos por caminhos alternativos, joins em tabelas fora da vista, logs globais ou consultas a um catálogo completo. Testar essa separação automaticamente.

### 6.4 Capacidade de reexecução como segundo fator

- **R-A:** etapas pertinentes disponíveis e replay validado.
- **R-B:** serviço histórico indisponível; respostas antigas preservadas podem alimentar somente o processamento posterior, para as entradas correspondentes.
- **R-C:** etapa determinística não reexecutável no ambiente permitido; código/ambiente parcial ou incompatível. A causa da indisponibilidade será registrada.

Usar o mesmo pacote de origem e aplicar restrições controladas, sem destruir artefatos originais. Algumas células são estruturalmente impossíveis; marcá-las como não aplicáveis, não como falha do método.

### 6.5 Modelo de registro

Usar entidades, atividades e relações de derivação compatíveis com PROV-DM. PROV descreve proveniência; uma relação de derivação não substitui evidência experimental de causa. [E1]

Cada tentativa terá identidade própria, mesmo com conteúdo igual. Preservar entrada efetiva, saída, código/patch executado, configuração, modelo retornado, endpoint/região, dependências, terminologia, estado operacional, início/fim, status, erros, consumo e relações de derivação. Não registrar credenciais. Hash de conteúdo não substitui identidade de evento.

Cada afirmação reconstruída receberá um estado: `armazenado`, `rederivado_verificado`, `inferido_compativel`, `refutado` ou `nao_determinado`, com evidências e limites. Não misturar inferências com fatos de execução capturados.

## 7. Referência causal: intervenções não são automaticamente causas

### 7.1 Alvo computacional

O objeto é a atribuição de uma mudança de saída em um pipeline de estrutura fixa, sob o conjunto de intervenções definido. Não se pretende inferir causalidade clínica nem uma causa ontológica única de uma chamada estocástica.

A primeira etapa divergente apenas gera candidatos. O conjunto de parâmetros alterados é um registro de intervenção, não o rótulo final de causa.

### 7.2 Conjuntos mínimos suficientes

Para uma associação `a` cuja presença muda entre referência `x0` e alternativa `x1`, seja `D` o conjunto de fatores efetivamente alterados. Para cada subconjunto admissível `S ⊆ D`, executar `x0` substituindo somente os fatores de `S` pelos valores de `x1`.

Um conjunto `S` é uma explicação mínima por inclusão quando:

- reproduz o estado final de `a` em `x1`;
- nenhum subconjunto próprio admissível de `S` reproduz esse estado.

Guardar a **família inteira de conjuntos mínimos**, não apenas o menor em cardinalidade. A definição é relativa ao contraste, granularidade dos fatores e universo de intervenções admissíveis.

Exemplo didático: o score inicial 0,59 não passa num limiar 0,60. Na alternativa, o limiar cai para 0,58 e o candidato muda para score 0,62. Cada mudança isolada inclui a associação. As explicações mínimas são `{limiar}` e `{candidato}`, não necessariamente `{limiar, candidato}`. Uma terceira alteração sem efeito não integra nenhuma explicação mínima.

### 7.3 Oráculo independente

No núcleo determinístico, limitar cada contraste a no máximo seis fatores binários candidatos efetivamente alterados: até `2^6 = 64` combinações. O avaliador enumerará todos os híbridos admissíveis, por uma implementação de controle separada da busca do método.

O núcleo começa nas respostas externas preservadas. Suas conclusões são condicionais a essas respostas. Alterar scores ou candidatos em um JSON é uma intervenção semissintética no artefato, não uma atualização real do ACM.

Quando houver mudanças a montante de um serviço, não reutilizar a resposta antiga para um texto novo. A combinação exige resposta correspondente já capturada, nova chamada permitida ou um simulador declarado. Sem isso, o contrafactual é indisponível.

### 7.4 Identificação e explicações alternativas

Construir pares de histórias executáveis que produzem a mesma evidência visível em uma vista restrita, mas diferem nos conjuntos mínimos relevantes. Testar a equivalência de observações e capacidades disponibilizadas ao método.

Nesses casos, acertar por acaso a história oculta não torna a conclusão exclusiva sustentada. A saída adequada é declarar alternativas ou insuficiência. A existência de duas histórias testemunhas demonstra ambiguidade no universo construído. A ausência de testemunha em uma busca incompleta não prova identificação global.

Saídas previstas: explicação verificada; família de explicações alternativas; compatível com variabilidade de referência; ausência de mudança relevante; informação insuficiente; orçamento esgotado; contrafactual indisponível. Falha de execução é outro estado, separado.

## 8. Famílias de cenários e matriz eficiente

| Família | Intervenção | Referência e cuidado |
|---|---|---|
| N — Controle nulo | Sem mudança deliberada; variação apenas de metadados de transporte ou repetição real | Não inventar causa de configuração; distinguir nulo local e nulo prospectivo |
| F — Filtros | Limiar de entidade, score de conceito ou regra de trait | Alterar uma regra por contraste básico; valores de borda explícitos |
| M — Mapeamento | Correspondência exata, fallback e política de categoria | Terminologia fixada; comparação estrutural não significa equivalência clínica |
| O — Ocorrências | Última ocorrência, seleção por score, top-1 versus conjunto de candidatos | Preservar ordem original; efeitos condicionais à resposta fornecida |
| P — Preparação | Duplicação da indicação, corte e substituição do nome | Serviço atual controlado ou simulador identificado; não reconstruir causalidade histórica por suposição |
| X — Causas combinadas | Dois/três fatores relevantes, um fator sem efeito e fatores com efeitos que se cancelam | Enumerar família mínima; não usar o rótulo da intervenção como resposta |
| I — Informação/capacidade | Remoção de evidência, divergência declarado/executado, restrição de replay | Mesma execução subjacente; medir identificação e abstenção |

As famílias partem dos achados de F1, mas terão textos, parâmetros e contrastes de teste separados dos usados no desenvolvimento.

### 8.1 Valores locais iniciais

Como grade inicial de calibração, variar o limiar de entidade em `0,55 / 0,60 / 0,65`, mantendo o de conceito e as demais regras fixos no contraste. O valor 0,60 é a referência do código V1 descrito em F1; os outros são propostas de experimento. [F1, §2.3]

As três políticas iniciais de mapeamento são: exata; exata com fallback nativo; projeção para categoria. Serão formalizadas no schema comum, com unidades não mapeáveis preservadas como tais. Não chamar a terceira de tradução terminológica validada.

### 8.2 Alteração do desenho de 27 configurações

O produto `3 traduções × 3 limiares × 3 mapeamentos` deixa de ser obrigação global. A base usa respostas fixadas e nove combinações locais, seguida de contrastes dirigidos de ocorrência, preparação e interação. A campanha de tradução é restrita a um subconjunto prospectivo.

Todos os perfis de evidência serão vistas das mesmas execuções. Assim, variar a quantidade de informação não exigirá repetir chamadas pagas nem mudar o experimento subjacente.

## 9. Campanha prospectiva de variabilidade

### 9.1 Isolamento de componentes

**ACM isolado:** mesma string de entrada, endpoint/região e configuração observável; registrar versão retornada a cada chamada. Manter tradução fixa.

**Tradução isolada:** mesmo texto em português, prompt e perfil; repetir sem cache. Comparar traduções antes de propagar ao ACM.

**Pipeline completo:** propagar as traduções obtidas, registrando as chamadas correspondentes. A variabilidade total não será automaticamente atribuída ao tradutor se o reconhecedor também variar.

A API documenta `ModelVersion` na resposta e não expõe um seletor de versão no corpo da requisição. O protocolo não depende de conseguir chamar hoje modelos históricos. [E2]

### 9.2 Perfis e repetições

Preservar a intenção do esboço: um modelo comercial; o mesmo com menor aleatoriedade quando esse controle existir; um modelo aberto com pesos identificados, se houver recursos. Fixar os nomes, versões, prompts e parâmetros na calibração. Não pressupor que temperatura zero ou pesos fixados garantam repetibilidade.

Planejamento inicial: **60 textos de desenvolvimento/calibração, dez execuções totais por perfil**. Se o piloto justificar e couber no orçamento, **150 textos do teste, cinco execuções totais por perfil**. Cinco totais significa referência mais quatro adicionais, não seis. Os grupos não se sobrepõem.

Para impedir reutilização indevida de controles, separar as chamadas por função antes da coleta: no piloto, seis referências e quatro realizações de avaliação por texto/perfil; no teste, três referências e duas realizações de avaliação. Apenas as referências adicionais ficam acessíveis em L3. Os pares-alvo são idênticos para L2 e L3. Realizações de avaliação não podem servir simultaneamente para estimar o nulo do mesmo caso.

Essa divisão é um ponto de partida de orçamento, não um desenho suficiente para testes estatísticos individuais por associação. A calibração poderá exigir ampliar repetições num subconjunto pré-especificado. Caso o orçamento permita somente cinco totais, usar comparações agregadas por grupo/família e estimativas de incerteza compatíveis; não apresentar três referências como estimativa precisa de uma cauda de 5% por texto. Limiares globais ou estratificados serão calibrados fora do teste, sem tratar textos diferentes como repetições idênticas.

Os números não asseguram precisão por associação rara. Quando insuficientes, ampliar a região de inconclusão, sem criar rótulos categóricos a partir de poucas chamadas.

### 9.3 Bloqueio temporal e controle

Intercalar e randomizar a ordem das condições dentro de blocos temporais, incluindo controles nulos em todos os blocos. Não executar todas as referências num dia e todas as alternativas em outro.

Uma mudança observada de versão do serviço inicia um novo estrato; não misturá-la ao nulo de mesma versão. Versão retornada igual não prova ausência de qualquer alteração interna. A conclusão será sobre variabilidade residual sob condições observáveis fixadas.

Chamadas falhas e tentativas terão registros próprios. Política de repetição por erro, limite de tentativas e tratamento de resposta incompleta serão fixados no piloto. Não substituir silenciosamente uma falha por resultado vazio.

### 9.4 Efeito estatístico versus explicação individual

Para uma associação, estimar a diferença de probabilidade de presença entre intervenção e referência dentro dos blocos comparáveis. Isso estima um efeito médio nas condições estudadas; não determina a causa única de uma realização individual.

Separar referências usadas para calibrar o método das repetições usadas para avaliar efeitos. Sob ruído, não definir a primeira chamada como verdade universal. Não significância não prova equivalência ao nulo; casos sem precisão suficiente serão inconclusivos.

### 9.5 Decisão após o piloto

Se não houver variação relevante no desfecho, registrar o resultado e seu limite de detecção. H2 não será declarada confirmada nem refutada universalmente. O estudo prossegue com H1 e a avaliação determinística. Simuladores estocásticos podem testar o mecanismo de abstenção, mas seus resultados ficam separados da evidência empírica de serviços reais.

## 10. Métodos de comparação

**B0 — Diferença dos resultados.** Referência descritiva, sem capacidade causal atribuída artificialmente.

**B1 — Configurações divergentes.** Lista fatores declarados que mudaram. Mede quanto a solução melhora em relação à heurística do esboço.

**B2 — Primeira divergência.** Localiza a primeira diferença de artefato/etapa acessível e reporta candidatos, sem concluir automaticamente causalidade.

**B3 — Referência nativa com replay.** Usa todas as evidências disponíveis em N1/N2 e pode rederivar intermediários e investigar intervenções sob o mesmo orçamento.

**M — Método proposto.** Constrói hipóteses a partir da proveniência, verifica intervenções admissíveis, procura conjuntos mínimos, reconhece alternativas e usa controles quando disponíveis.

O estudo comparará M com e sem controle de variabilidade e com L2-R versus L2-M. Comparações de informação usam o mesmo algoritmo; comparações de algoritmo usam a mesma vista. Não mudar as duas coisas simultaneamente e atribuir todo o ganho à proveniência.

### 10.1 Comparadores publicados

Why-Diff compara traços de proveniência e diferenças de workflows; BugDoc explora configurações de processos para investigar falhas. São candidatos relevantes, já relacionados no esboço. [E3–E4; F3, §4]

Na fase inicial, avaliar uma implementação ou adaptação fiel de pelo menos um deles. Para BugDoc, definir explicitamente como a mudança da associação se transforma no predicado de avaliação; para Why-Diff, definir a tradução do pipeline em traços comparáveis. Documentar mudanças e testes de fidelidade. Uma heurística própria não receberá o nome de uma implementação desses trabalhos.

Se não houver comparação executável viável, registrar a limitação e restringir alegações de superioridade/novidade. Revisão conceitual não substituirá medição experimental.

### 10.2 Recursos e acesso

Todos os métodos terão a mesma interface de evidências/intervenções e limites equivalentes. Medir dois regimes: disponibilidade suficiente para completar o espaço finito e orçamento restrito. Planejar curvas de 16, 32 e 64 avaliações locais por contraste, refinadas na calibração.

Cobrar também a reconstrução inicial, a leitura de artefatos, o processamento em lote e chamadas externas. Compartilhamento de computação será permitido simetricamente, com custo bruto e amortizado. Não excluir o custo das referências de L3 nem confundir custo de construir o benchmark com custo de operar o método.

## 11. Métricas e análise estatística

### 11.1 Desfecho primário

**Cobertura de atribuições corretas e sustentadas:** fração dos casos elegíveis em que a saída satisfaz a referência e o grau de certeza permitido pela evidência. Distinguir da cobertura bruta, que conta qualquer resposta categórica.

**Risco seletivo:** proporção de respostas categóricas incorretas ou indevidamente exclusivas entre as respostas categóricas emitidas. Comparar cobertura a risco alvo de 5%, com limiares do método calibrados antes do teste. Reportar o risco efetivamente observado e seu intervalo, mesmo quando ultrapassar a meta.

### 11.2 Desfechos secundários

Precisão/recall/F1 por classe de causa; correspondência exata de cada conjunto mínimo; precisão e recall da família de conjuntos quando o oráculo é completo; taxa de exclusividade indevida; identificação de alternativas; abstenção por motivo; custo; estabilidade da explicação.

A união de causas será uma análise auxiliar: ela não distingue `{A,B}` como interação de `{{A},{B}}` como explicações alternativas. Uma lista de todas as causas possíveis não contará como explicação correta.

No nulo, medir falsas atribuições por contraste e, como medida principal de controle, a fração de grupos com pelo menos uma falsa atribuição. Mudanças sem efeito e resultados sem mudança permanecem no denominador pertinente.

### 11.3 Dependência e incerteza

Reamostragem pareada por grupo documental, preservando suas associações, contrastes e repetições. Para a campanha real, manter também a estrutura de blocos temporais; usar análise hierárquica ou reamostragem que reflita os dois eixos. Escolher e validar o procedimento na calibração.

Planejamento inicial: intervalos de 95% e 2.000 reamostragens, com verificação de estabilidade numérica. Não tratar todos os pares de repetições como independentes. Em eventos raros ou zero falhas, não usar um bootstrap degenerado como prova de risco zero; empregar limite compatível com a unidade independente e registrar suas suposições.

Pré-especificar três contrastes primários: L2-R versus L2-M no replay validado; ganho da evidência efetiva nas perdas dirigidas; L3 versus L2 na campanha pertinente a H2. Ajustar a multiplicidade das conclusões confirmatórias, por procedimento fixado antes do teste. As demais comparações serão secundárias/exploratórias.

Não inferioridade exige intervalo compatível com a margem, não apenas ausência de diferença significativa. Relatar tamanhos de efeito, intervalos, número de grupos e custos, não somente valores-p.

### 11.4 Custo

Registrar bytes brutos e deduplicados por execução/documento, armazenamento amortizado por associação, tempo/CPU/memória, replays, novas chamadas e custo monetário medido. Armazenamento por associação sozinho favorece configurações que produzem mais associações; por isso os demais denominadores são obrigatórios.

Apresentar a fronteira entre cobertura, risco, armazenamento e computação. Não condensar tudo em uma nota ponderada sem pesos e análise de sensibilidade previamente definidos.

## 12. Avaliação documental — Q3

Manter o orçamento inicial de **150 textos distintos no total**: 20 no piloto de anotação, excluídos da avaliação final, e 130 do teste. Entre os 130, 50 terão dupla anotação independente; os 80 restantes terão anotação única, com essa limitação explicitada. A política evita contar textos de treinamento dos anotadores como teste. [F3, §5]

As 130 unidades serão escolhidas entre grupos de teste, preferencialmente no subconjunto prospectivo de 150, com probabilidades de inclusão registradas. A estratificação por mudança/cobertura terapêutica poderá usar saídas congeladas apenas para amostragem, sem ajustar o método e sem mostrá-las aos anotadores. Usar pesos na estimativa populacional.

Anotar integralmente o suporte na seção portuguesa de indicações escolhida, não apenas validar associações emitidas: caso contrário, não há base para medir revocação. Fixar o documento de referência por versão. Em cenários com entrada editada, usar a entrada daquela condição; não avaliar texto alterado contra uma referência documental incompatível.

Categorias CID-10 são a unidade principal; subcategorias só quando sustentadas pelo texto. Não inferir indicação a partir de menção em contraindicação ou de conhecimento externo. A edição de texto usada como intervenção não pode ser apresentada como bula oficial real.

Publicar guia, evidências textuais, concordância antes de adjudicação, métricas do subconjunto duplamente anotado e da amostra ampliada. A precisão dos rótulos de anotador único é uma limitação. Se faltarem especialistas, reduzir Q3 e não produzir conclusão clínica; a avaliação computacional H1/H2 continua separada.

## 13. Orçamento e redução de escopo

O núcleo local não exige novas chamadas ao ACM. Ele usa respostas preservadas e o replay. A campanha paga será liberada apenas depois de medir elegibilidade, custos e informação adicional obtida no piloto.

Com `n` textos, `p` perfis e `r` execuções totais, o orçamento-base de tradução é `n × p × r`, antes de erros e tentativas. Para ACM, somar as chamadas de entrada fixa, as chamadas para cada tradução propagada e as repetições adicionais. A campanha não pressupõe que os mesmos resultados possam servir a duas entradas diferentes.

Exemplo de planejamento, não compromisso de execução: 150 textos × 3 perfis × 5 execuções = 2.250 traduções no teste. Propagar cada uma implica até 2.250 chamadas-base ao ACM, além do bloco com tradução fixa e de repetições planejadas. O piloto de 60 × 3 × 10 adiciona 1.800 traduções. Esses totais deverão ser confrontados com preços e consumo medidos antes de autorizar a campanha.

Preservar o teste bloqueado, o comparador nativo forte e o oráculo. Cortar primeiro: o terceiro perfil de tradução; cruzamentos não essenciais; cenários a montante caros; quantidade de textos prospectivos, com perda de precisão declarada. Nunca reduzir controles nulos para manter apenas casos de sucesso.

## 14. Congelamento e prevenção de vazamento

Antes do teste, congelar protocolo, elegibilidade, grupos, sementes, algoritmos, adaptadores, fatores, cenários, terminologia, perfis, políticas de erro, orçamentos, margens, métricas, regras de abstenção e análise estatística.

Separar fisicamente o pacote de verdade do avaliador das vistas do método. Rótulos, nomes de tratamentos e resultados do oráculo não entrarão em nomes de arquivos, IDs ou logs acessíveis ao método. Configurações e artefatos legítimos continuam visíveis conforme o perfil: ocultar o rótulo causal não significa esconder toda diferença observável.

Testar isolamento e registrar acessos. Mudança de código após abrir o teste exige novo número de versão e classifica a análise como exploratória ou exige um novo teste não consultado. Uma segunda revisão/execução independente é desejável; não será alegada independência se o mesmo processo que gerou a referência apenas validou a própria saída.

## 15. Entregas, ordem e critérios de passagem

| Marco | Entrega | Critério para avançar |
|---|---|---|
| P0 — Evidência | Manifesto de artefatos e reprodução histórica | Diferenças documentadas; nenhuma suposição tratada como dado capturado |
| P1 — Especificação | Contrastes, chaves, fatores, estados de evidência e igualdade | Exemplos pequenos com respostas esperadas e hipóteses falsificáveis |
| P2 — Benchmark | Gerador, oráculo exaustivo, vistas N1/N2/L1–L3 e restrições | Verdade separada; híbridos compatíveis; testes de isolamento aprovados |
| P3 — Comparadores e piloto | Referência nativa com replay, método, comparador publicado e campanha pequena | Custos medidos; fidelidade comparada; precisão e variabilidade caracterizadas |
| P4 — Pré-registro | Protocolo confirmatório congelado e conjunto de teste bloqueado | Todos os parâmetros definidos sem resultados de teste |
| P5 — Execução | Teste local, campanha prospectiva autorizada e anotação | Registro completo de casos, falhas e desvios; nenhuma seleção posterior silenciosa |
| P6 — Análise | Resultados, ablações, pacote reproduzível e limitações | Hipóteses avaliadas com critérios registrados; estudo histórico separado do causal |

Compatibilidade com o cronograma original de 24 meses: consolidar evidências/pilotos nos meses 1–6; instrumentação e método inicial nos meses 7–12; congelamento até o mês 15; teste/análise/artigo nos meses 16–18; dissertação e defesa nos meses 19–24. São marcos de planejamento acadêmico, não previsão de conclusão antecipada. [F3, §7]

### 15.1 Pacote de reprodução proposto

Arquivos esperados: `protocol.md`, `sources_manifest.json`, `corpus_groups.csv`, `split_manifest.csv`, `scenario_catalog.yaml`, `evidence_views.yaml`, `replay_manifest.json`, `oracle/`, `baselines/`, `runs/`, `analysis/`, `annotation_guide.md` e `deviations.md`.

Esses nomes especificam entregas futuras; este documento não afirma que tais arquivos já foram implementados. Os artefatos privados/licenciados excluídos das versões abertas permanecem fora do pacote. Originais são imutáveis; transformações têm hashes e histórico próprio.

## 16. Resultado científico esperado e limites

O resultado não será demonstrar a priori que o HealDB carecia de proveniência. Será determinar, no recorte estudado, quando a preservação existente basta, quando recomputar é alternativa adequada a armazenar, quando evidências adicionais mudam a conclusão e quando a única resposta sustentada é admitir alternativas ou insuficiência.

A contribuição precisa ser um método e uma avaliação contra referências fortes. Uma coleção de defeitos históricos, um sistema de logs ou uma confirmação de que mais informação facilita auditoria não constituem, isoladamente, a contribuição pretendida. As conclusões quantitativas permanecerão limitadas ao HealDB e às famílias/provedores/condições observadas.

## Referências e origem das decisões

**F1.** `PROVENIENCIA_NLP_V1.md`, levantamento fornecido de 29/09/2026. Usar as ressalvas das §§2.4, 4.4 e 8. Frases sobre o texto executado e ausência de código serão interpretadas dentro do espaço de hipóteses e do histórico público examinados.

**F2.** `RECONSTRUCAO_V1_MATRIZ(1).md`, levantamento fornecido de 29/09/2026, incluindo a errata. A igualdade dos SQLs remove exclusivamente a linha `-- Dump completed on`; não implica igualdade bruta dos arquivos compactados.

**F3.** `Esboco_HealDB_IC_Unicamp.pdf`, plano de pesquisa de Vinícius André de Santana, três páginas. Este protocolo preserva Q1–Q3 e revisa operacionalmente hipóteses, referências e experimentos.

**E1.** Moreau, L.; Missier, P. (eds.). PROV-DM: The PROV Data Model. W3C Recommendation, 30/04/2013. Referência para entidades, atividades e derivação, não para identificação causal.

**E2.** Amazon Web Services. InferICD10CM. Amazon Comprehend Medical API Reference. Documentação consultada para estrutura de requisição/resposta e versão retornada; revalidar o contrato ao implementar o adaptador.

**E3.** Thavasimani, P.; Cała, J.; Missier, P. Why-Diff: Exploiting Provenance to Understand Outcome Differences from Non-Identical Reproduced Workflows. IEEE Access, 7, 34973–34990, 2019. DOI 10.1109/ACCESS.2019.2903727.

**E4.** Lourenço, R.; Freire, J.; Shasha, D. BugDoc: Algorithms to Debug Computational Processes. SIGMOD, 2020. DOI 10.1145/3318464.3389763; arXiv:2004.06530.

As especificações experimentais, margens, amostras e regras propostas neste documento são decisões novas de planejamento; não são atribuídas a E1–E4.

## Identificação dos relatórios utilizados

- `PROVENIENCIA_NLP_V1.md` — SHA-256 `bd466b36d8b70f76119299a0be4138eccf04920f6cb7eb211ea86d31bdedd1f4`; 33.897 bytes.
- `RECONSTRUCAO_V1_MATRIZ(1).md` — SHA-256 `856d5c31b7668d5807ac25fcde5942e8ed0c225a6279565b7a2f110b50ebd515`; 21.480 bytes.

Os hashes identificam os dois arquivos Markdown lidos nesta elaboração; não certificam os dumps, scripts e saídas externas citados dentro deles.
