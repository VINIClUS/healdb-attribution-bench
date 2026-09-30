# Registro de decisões

Cada entrada tem data, quem decidiu e o motivo. Decisões do usuário são citadas como tal; as demais foram tomadas pela sessão principal sob autoridade delegada ("tem permissão para ... aprovar decisões e criações/edições por mim", 2026-09-30).

## 2026-09-30 — usuário

- **Repositório.** A implementação mora neste repositório novo, git local e sem remoto.
  - O ThesisBench fica intocado: o remoto privado dele contém outro produto.
  - Nenhum arquivo rastreado do HealDB é alterado.
- **Chamadas pagas.**
  - Primeiro um smoke test do ACM, depois o piloto §9.2 (60 textos dev/cal × perfis × 10 execuções).
  - Teto rígido cumulativo de US$30, contando o smoke test.
  - Perfil AWS default, região us-east-2; tradução via Bedrock.
  - A campanha de teste (150 × 5) não está autorizada.
- **Teste bloqueado.** Parar no congelamento P4. O teste fica selado até o usuário registrar o pré-registro e abri-lo.

## 2026-09-30 — sessão principal (autoridade delegada)

- Documentação humana em português; código e comentários em inglês.
- Sem push nem publicação.
- Q3 limitado a um kit de anotação (guia, amostrador, planilhas cegas, métricas de concordância), sem anotação humana nesta fase.
- O SPEC (`docs/SPEC.md`) é aprovado pela sessão principal no lugar do usuário, após auditoria Opus independente.
- Gerentes Opus são sessões headless (`claude -p --model opus`). O ambiente força todo subagente a ser Sonnet (`CLAUDE_CODE_SUBAGENT_MODEL=sonnet`, `_FORCE=1`), o que realiza "Opus gerencia Sonnet".
- Dados derivados, verdade, vistas e execuções ficam em `/home/vinicius/hab-data`, fora do repositório.
- Grupos documentais: união de PT normalizado idêntico ou quase duplicado (Jaccard de shingles ≥ 0,90, limiar fixado a priori) com EN idêntico. Nenhuma bula é compartilhada entre medicamentos.
- Espaço de comparação principal: CID-10/OMS. Saídas CID-10-CM são projetadas e rotuladas "projeção estrutural" (§5.1).

## 2026-09-30 — perfis de tradução da campanha (sessão principal)

- **Disponibilidade.** Verificada no Bedrock us-east-2 com as APIs gratuitas de controle `ListFoundationModels` e `GetFoundationModelAvailability`. Os preços vêm da AWS Price List, `AmazonBedrock`, `regionCode=us-east-2`.
- **Perfis escolhidos:**
  - **Comercial:** `amazon.nova-lite-v1:0` (on-demand), com a amostragem padrão do serviço.
    - Preço: US$0,00006 por 1K tokens de entrada e US$0,00024 por 1K de saída.
  - **Comercial com menor aleatoriedade:** o mesmo modelo com `temperature=0`. Temperatura zero não é presumida determinística (§9.2).
  - **Pesos abertos identificados:** `meta.llama3-3-70b-instruct-v1:0` (on-demand), com a amostragem padrão.
    - Preço: US$0,00072 por 1K tokens, entrada e saída.
- **Anthropic descartado.** Modelos Anthropic no Bedrock criam uma assinatura do AWS Marketplace na primeira invocação (`agreementAvailability=NOT_AVAILABLE` para Haiku 4.5). Isso é aceitar termos em nome do usuário, e não foi autorizado. Nova e Llama já constam com `agreementAvailability=AVAILABLE`.
- **Tradutor histórico indisponível.** O tradutor histórico (OpenAI, GPT-3.5 segundo a documentação) não é reproduzível: não há chave OpenAI e o modelo foi descontinuado.
  - A campanha mede a variabilidade de tradutores atuais. Não recupera traduções históricas, o que o §9.1 não exige.
  - O prompt histórico e o corte de 6000 caracteres são mantidos.

## 2026-09-30 — GATE 2: SPEC v0.1 (sessão principal)

**Veredito da auditoria.** O auditor Opus independente deu "aprovar com correções", com 3 achados bloqueantes, 13 importantes e 5 menores (`docs/auditorias/gate2_spec.md`). Aceito o veredito.

O SPEC é aprovado **na condição de v0.2**: o lead β aplica as correções abaixo, e a sessão principal reconfere as seções alteradas com a suíte verde antes do β3 e do lead γ.

**Aplicar antes do β3 e do γ.** Achados A01, A02, A03, A09, A13 e A14, mais todas as correções que mudam o texto do SPEC: A04, A05, A06, A07, A08, A10, A11, A12, A18, A20 e A21.
- Os achados de P4 que também mudam o SPEC entram agora, para que o γ implemente a semântica final.
- Ficam para a β3: as medições de A15 e os testes diferenciais de A19.

**Decisões sobre os itens [revisar] do lead β:**
1. **H1a (R09, A05).**
   - O orçamento primário passa a `b = 16`; os orçamentos 32 e 64 ficam secundários.
   - Em L2-R, valem certificados `trace` derivados dos traços devolvidos por avaliações pagas (constam do log).
   - Um `Δ*` de variância zero é relatado como "identidade por construção", nunca como evidência de não inferioridade.
   - A parte de armazenamento de H1a tem um critério descritivo pré-declarado: razão de bytes deduplicados L2-R/L2-M, com IC, e tempo de reconstrução.
2. **H1b (R17, A06).** Aceito o agregado de dois estratos, com as definições de A06:
   - denominador comum aos dois braços;
   - estimador de razão conjunto por consulta;
   - guarda de risco no percentil 97,5;
   - regra para reamostras sem categóricas;
   - A1 fora dos estratos.
3. **Modelo de variantes K (§4.3, A07).** Aceito como decisão de modelagem, com três condições:
   - cada hipótese de K cita F1;
   - H1b é relatada também com `K = ∅`, como sensibilidade pré-declarada;
   - parte das execuções novas da família I realiza a variante `alt`.
4. **Cobertura primária só sobre alteradas (R13, A18).** Aceita, com a justificativa escrita no SPEC. Não vale na campanha.

**Outras decisões:**
- **Risco seletivo (A04).** Para a calibração a 5% e para a guarda de H1b, usa-se o risco sobre categóricas comprometidas (sem `nao_comprometido`). O risco literal de §11.1 também é relatado.
- **α dos limites de evento zero (A08).** α = 0,025 unilateral, coerente com as inferências primárias. O dimensionamento usa o nível do pior caso de Holm, e `p_H2 = max(p_i, p_ii)`.
- **`top1` dentro de um grupo de `Id` (A02).** O normativo é o comportamento de `pipeline/core.py`, que reproduz as tabelas V2 com 0 diferenças. O SPEC o descreve citando o código. Onde os dados V2 não fixam o caso (empates), vale o comportamento do núcleo. O lead α adapta `pipeline/semantics.dummy` às regras corrigidas, com um teste de solidez por propriedade.
- **Exemplo público de §7.2 (X(iii), A12).** Fica restrito a dev/cal e nunca entra em teste.

## 2026-09-30 — GATE 2: SPEC v0.2 aprovado (sessão principal)

A sessão principal reconferiu as seções alteradas:
- a seção 16 (changelog);
- 8.3, com a partição dos estados provada e EX-24;
- 9.2, com o passo 0, a tabela de aceitação e EX-21 (e)–(h);
- 6.3, com a completude da BFS; EX-28 foi recalculado à mão.

A suíte está verde no commit `188123a` do lead β: `tests/test_spec_examples.py` com 86 testes e o total com 512.

O SPEC v0.2 é o documento normativo da onda 2 (β3 e γ). Correções posteriores entram como v0.2.x, com changelog, e só por decisão registrada aqui.
