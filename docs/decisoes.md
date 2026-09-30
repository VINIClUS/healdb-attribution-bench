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
