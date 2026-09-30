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
