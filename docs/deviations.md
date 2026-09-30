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
- **Efeito:** o dev ultrapassa a meta de 200, como o próprio protocolo prevê.
- **Tamanho efetivo** (`repro/split_manifest.csv`, merge `8740d92`):

| partição | grupos | medicamentos |
|---|---|---|
| dev | 461 | 1.082 (inclui todos os inspecionados, entre eles os 278 da amostra de `extend`) |
| cal | 200 | 286 |
| test (selado) | 600 | 822 |
| reserva | 3.826 | 5.257 |

## D5 — Implementação da campanha (lead δ, aceito pela sessão principal, 2026-09-30)

- **Seções:** §9.2, §9.3, §13.
- **Descrição:**
  - **Retentativas do botocore.** A intenção do brief é uma requisição HTTP por tentativa. Ela foi realizada com `total_max_attempts=1`, porque no botocore `max_attempts` conta só as retentativas.
  - **Controles nulos.** O piloto não tem intervenção, então toda repetição com entrada fixa é um nulo. "Nulos em todos os blocos" foi lido assim: todo bloco temporal contém as três condições e as duas funções (referência e avaliação).
  - **Pipeline completo** sem o mascaramento `<drug>`, que não é reproduzível a partir do código comitado da V2.
  - **Falhas** são conciliadas no ledger pelo pior caso, porque não se sabe se a AWS as cobra. O ledger superestima o gasto, nunca o subestima.
- **Efeito:** o teto de US$30 fica conservador. O custo real pode ser menor que o do ledger.

## D6 — Campanha bloqueada pela verificação da conta AWS (2026-09-30)

- **Seções:** §9 (Estudo C) e §13.
- **Descrição:** a conta do perfil AWS default, em us-east-2, ainda não pode usar os serviços de dados. Tudo está registrado em `docs/campanha/execucoes.md`.
  - Smoke test do ACM (`smoke-01`, 100 chamadas): todas falharam com `SubscriptionRequiredException`.
  - Canário Bedrock (`canary-bedrock-01`, 3 chamadas): todas falharam com `AccessDeniedException`, "account is currently being verified".
  - Nenhuma chamada foi aceita pelo serviço. O ledger conciliou as 103 falhas pelo pior caso (US$0,4925), conforme D5.
- **Efeito:** o piloto §9.2 não começa até a conta ser liberada.
  - A sessão principal repete uma sonda de 2 chamadas (pior caso US$0,002) antes de retomar.
  - Nada que dependa de chamadas pagas entra no relatório enquanto isso.

## D7 — Decisões do SPEC relativas ao protocolo (GATE 2, 2026-09-30)

Origem: lead β (R-ids de `docs/analise/00_analise_protocolo.md`), auditoria (A-ids de `docs/auditorias/gate2_spec.md`) e decisões da sessão principal (`docs/decisoes.md`, "GATE 2").

| id | seção | desvio ou especificação | motivo |
|---|---|---|---|
| D7.1 | §11.1 | Cobertura primária só sobre associações alteradas (R13). As inalteradas alimentam o controle nulo. | No núcleo determinístico, os finais revelam a mudança. Não vale na campanha, onde `Q_u` não é trivial. |
| D7.2 | §8 | Família P só catalogada (R20): sem chamadas novas nem simulador; referência `contrafactual_indisponivel`, fora dos denominadores. | Não há respostas armazenadas para as variantes de preparação. |
| D7.3 | §11.3 | H2 entra no Holm com p = 1. O piloto dev/cal é exploratório (P-β2). | A campanha de teste não está autorizada. O FWER fica controlado, ao custo de poder. |
| D7.4 | §6.2 | L3 ≡ L2 no núcleo determinístico, sem execução separada. | As referências repetem x0 quando não há variabilidade. |
| D7.5 | §4.3, §14 | Níveis queimados (P-β1): todo valor citado em `docs/design/`, `docs/SPEC.md` ou nos exemplos fica fora da lista selada de teste. Inclui os candidatos 0,575 e 0,625 do desenho §C. | Esses valores foram expostos antes do congelamento. |
| D7.6 | §12 | Os 20 textos do piloto de anotação saem de dev/cal (P-β4). | O guia pode ser pilotado antes de abrir o teste. |
| D7.7 | §6.4, §7.4 | Identificação em R-C e sem vínculo ao código usa o espaço de variantes K (A07). H1b é relatada também com `K = ∅`. | O protocolo não fixa o modelo de "código/ambiente parcial". |
| D7.8 | §11.1 | Calibração a 5% e guarda de H1b sobre o risco das categóricas comprometidas (A04). O risco literal também é relatado. | Uma lista longa de `alternativas` dilui o risco literal. |
| D7.9 | §2.1, §11.3 | H1a com orçamento primário `b = 16` (A05). Variância zero é relatada como identidade por construção. | Com `b = 64` a não inferioridade é trivial. |
| D7.10 | §8 | O exemplo público de §7.2 fica restrito a dev/cal (A12). | É público e cairia na região de H1a. |
