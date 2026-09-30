# Desvios e limitações registrados (protocolo v0.2)

Registro cumulativo. Cada entrada traz data, seção do protocolo, descrição, motivo e efeito esperado.

## D1 — Nomes de arquivo das fontes (2026-09-30)

- **Seção:** Referências F2 e F3.
- **Descrição:**
  - O protocolo cita `RECONSTRUCAO_V1_MATRIZ(1).md`. O arquivo local é `HealDB/doc/RECONSTRUCAO_V1_MATRIZ.md`, com o mesmo SHA-256 citado.
  - O protocolo cita `Esboco_HealDB_IC_Unicamp.pdf`. O arquivo local é `~/Downloads/Esboco_revisado_HealDB_IC_Unicamp(2).pdf`.
- **Efeito:** nenhum. A identidade de todos os arquivos está em `docs/protocolo/SHA256SUMS`.

## D2 — Exposição do corpus inteiro durante o planejamento (2026-09-30)

- **Seções:** §4.3 e §14.
- **Descrição:** antes da definição dos splits, subagentes de planejamento calcularam sobre as 7.447 respostas V1, incluindo os futuros grupos de teste:
  - o contraste real "pós-processamento V1 × V2" (64 híbridos);
  - a distribuição de formas de famílias mínimas (804 tabelas-verdade distintas);
  - a repetibilidade do ACM entre textos idênticos.
- **Efeito e mitigação:**
  - Adequação do universo de identificação, cotas de forma e calibração usam só dev/cal.
  - Nos grupos de teste, o bundle real `V1_TO_V2` não conta como novidade: fica fora do conjunto confirmatório e é reportado à parte.
  - A novidade do teste vem de parâmetros e contrastes exclusivos, selados.
  - O corpus histórico conhecido já era limitação declarada (§4.3).

## D3 — Números de rascunho dos subagentes (2026-09-30)

- **Descrição:** os números em `docs/design/*.md` vêm de computações de rascunho de subagentes.
- **Efeito e mitigação:** nenhum entra em relatório sem re-derivação por código versionado neste repositório.

## D4 — Partição de desenvolvimento maior que 200 textos (esperado)

- **Seção:** §4.3.
- **Descrição:** o protocolo manda incluir no desenvolvimento as bulas inspecionadas individualmente. Só a amostra de `extend` (`out/extend_amostra.csv`) cobre cerca de 278 medicamentos.
- **Efeito:** o dev ultrapassa a meta de 200, como o próprio protocolo prevê. O tamanho efetivo será registrado quando os splits forem gerados.
