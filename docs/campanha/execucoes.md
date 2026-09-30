# Execuções da campanha (Estudo C) — registro da sessão principal

Só a sessão principal executa chamadas pagas. Todas usam o plano `repro/campaign_plan.yaml` e o ledger cumulativo `/home/vinicius/hab-data/campaign/ledger.jsonl`, com teto de US$30.

Cada execução guarda sua proveniência em `/home/vinicius/hab-data/campaign/<run_id>/`:
- `prov.jsonl`;
- `run.json`;
- `raw/`, com os corpos HTTP brutos.

As agendas ficam em `/home/vinicius/hab-data/campaign/schedules/`.

## Agendas

| arquivo | origem | chamadas | pior caso (1 tentativa) |
|---|---|---|---|
| `smoke.json` | `plan-smoke` | 100 ACM (20 textos dev × 5, `ds_text_submitted` exato da V2) | US$0,4875 |
| `pilot.json` | `plan-pilot` | 600 ACM isolado, 1.800 traduções, 1.800 ACM do pipeline | US$96,18 (limite rígido; o esperado é bem menor, ver abaixo) |
| `canary_bedrock.json` | subconjunto do piloto: 1 tradução por perfil, o texto PT mais curto, bloco 0 | 3 | US$0,005 |
| `probe.json` | 1 ACM (o texto do smoke mais curto, 118 caracteres) + 1 tradução Nova Lite | 2 | US$0,002 |

**Estimativa do piloto** (`estimate`, textos reais):
- ACM isolado: US$2,72, exato.
- Pipeline completo: valor esperado de US$8,16. É um proxy e não um limite: cada texto é precificado pelo texto ACM da V2 do mesmo medicamento.
- Traduções: no máximo US$3,46.

O esperado total fica abaixo de US$15, dentro do critério de seguir (≤ ~US$25). Mesmo assim, a execução paga reserva o custo exato de cada texto e para no teto.

## Execuções

| run_id | data (UTC−3) | agenda | resultado | ledger |
|---|---|---|---|---|
| `smoke-dry` | 2026-09-30 | `smoke.json` | simulação: 100 chamadas planejadas, nada gravado | — |
| `smoke-01` | 2026-09-30 ~15:00 | `smoke.json` | 100/100 falhas `SubscriptionRequiredException` ("The AWS Access Key Id needs a subscription for the service") | US$0,4875 (pior caso das falhas) |
| `canary-bedrock-01` | 2026-09-30 ~15:10 | `canary_bedrock.json` | 3/3 falhas `AccessDeniedException` ("Your account is currently being verified…") | US$0,0050 (pior caso das falhas) |

**Total do ledger:** US$0,4925, todo de falhas conciliadas pelo pior caso (D5). O serviço recusou as requisições antes de processá-las.

**Situação:** a campanha está bloqueada pela verificação da conta (D6). A mensagem da AWS diz que a verificação costuma levar menos de 2 horas.
