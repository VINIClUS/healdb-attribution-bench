# Campanha prospectiva (Estudo C) — como o piloto implementa o §9

Documento da implementação em `src/habench/campaign/`. Descreve o que o código faz. Não relata resultados: nenhuma
chamada paga foi feita por este código até agora.

## 1. Autorização e dinheiro

- **Padrão: simulação.** Sem `--paid`, `run` faz uma simulação. Nenhum cliente AWS é criado, nada é escrito no ledger
  nem no diretório da execução, e nada espera.
- **Chamada real exige quatro condições simultâneas:**
  - `HAB_PAID_CALLS=1` no ambiente;
  - a flag `--paid`;
  - `--budget-usd <x>`, com x > 0;
  - preço no plano para todo modelo usado. Identificadores `<...>` são marcadores e nunca têm preço.

  Falta de qualquer uma encerra o comando antes de criar clientes. Só a sessão principal executa chamadas pagas.
- **Ledger cumulativo:** `/home/vinicius/hab-data/campaign/ledger.jsonl`, com lock de arquivo.
  - Antes de **cada tentativa**, reserva-se o pior caso.
  - A tentativa é recusada se `gasto + reserva` ultrapassar o teto do plano (US$ 30, cumulativo, smoke incluído)
    ou o orçamento da execução (`--budget-usd`).
  - Depois da tentativa, concilia-se o custo:
    - ACM com sucesso: unidades da tabela de preços, calculadas a partir dos caracteres enviados;
    - Bedrock com sucesso: tokens informados em `usage`;
    - falha: pior caso, porque não se sabe se foi cobrada.
  - Reserva sem conciliação (queda do processo) conta como gasta. Na retomada, é conciliada pelo pior caso e
    registrada como tentativa interrompida.
- **Pior caso por tentativa:**
  - ACM: `max(1, ceil(caracteres/100)) × US$ 0,0005`. Preço da lista us-east-2 de 2026-09-11, guardado no plano,
    não no código.
  - Bedrock: bytes UTF-8 do prompt × preço de entrada, mais `max_tokens` × preço de saída.
  - Na estimativa prévia, a chamada ACM do pipeline completo usa o limite de 10.000 caracteres, porque o texto ainda
    não existe. Na execução, a reserva usa o texto efetivo.
- **Retentativas:** as internas do botocore estão desligadas (`total_max_attempts=1`, uma única requisição HTTP por
  chamada). O runner repete só os códigos de erro listados no plano, até `retry.max_attempts`. Cada tentativa tem
  reserva, registro e identificador próprios, e está ligada à anterior por `wasInformedBy`.

## 2. Textos e seleção (§§4.1, 9.1–9.2)

- A seleção lê `repro/split_manifest.csv` e usa apenas grupos `dev`/`cal`. Pedir a partição `test`, ou um grupo de
  teste por identificador, levanta `SealedError`. Textos de grupos de teste nunca são lidos.
- **Um texto por grupo:** o medicamento elegível de menor id.
  - Elegível para o ACM: `ds_text_submitted` da V2 presente, não vazio e com até 10.000 caracteres.
  - Elegível para tradução: `ds_indication` em português presente, não em branco e com mais de 10 caracteres. O
    HealDB zera traduções de indicações com comprimento ≤ 10.
  - Todo medicamento pulado entra em `Schedule.excluded` com o motivo. Nada é descartado em silêncio.
- **Smoke:** 20 grupos de `dev`, sorteados com a semente do plano; 5 chamadas ACM por texto sobre o
  `ds_text_submitted` exato da V2.
- **Piloto:** 60 grupos de `dev ∪ cal`, estratificados pela coluna `stratum` com alocação proporcional (maiores
  restos). Grupos inteiros.

## 3. Os três blocos de condição (§9.1)

| condição | serviço | entrada | repetições por texto |
|---|---|---|---|
| ACM isolado | InferICD10CM | `ds_text_submitted` da V2, exato (com o mascaramento `<drug>` que a V2 enviou) | 10 |
| Tradução isolada | Bedrock Converse | `ds_indication` em português, exato, cortado em 6.000 caracteres | 10 por perfil (3 perfis) |
| Pipeline completo | InferICD10CM | `"What this medication is indicated for:\n" + s.strip() + "\n\n"`, cortado em 10.000, com `s` = cada tradução obtida | uma por tradução |

- **Prompt histórico:** exatamente `Translate to English and return only the translation: {texto}`, sem strip,
  como em `translate_leaflet_sections.py` (idêntico em 405a10c e HEAD).
- A chamada é uma única mensagem de usuário, sem prompt de sistema e sem cache de prompt. `max_tokens` é fixo no
  plano; a temperatura vem do perfil e não é enviada quando o perfil usa o padrão do serviço.
- **Pipeline completo:** sem mascaramento do nome do medicamento, pois o mascaramento pretendido da V2 não é
  reproduzível a partir do código comitado.
- **Contagens do piloto:** 600 chamadas ACM isoladas, 1.800 traduções (60 × 3 × 10, o exemplo do §13) e 1.800 ACM
  do pipeline, antes de erros e retentativas. `estimate` calcula os limites de custo a partir dos textos reais.
- **Perfis (§9.2):** comercial; o mesmo comercial com temperatura 0; pesos abertos. Os ids de modelo ficam como
  marcadores no template, e a sessão principal os fixa com os preços antes da execução. Temperatura 0 não é tratada
  como garantia de repetibilidade.

## 4. Funções fixadas antes da coleta (§9.2)

- Para cada unidade (texto no ACM isolado; texto × perfil na tradução), uma permutação com semente escolhe **6
  repetições de referência e 4 de avaliação**.
- Cada chamada ACM do pipeline herda a função, o bloco, o perfil e a repetição da tradução que a alimenta. Uma
  tradução de referência nunca alimenta uma chamada de avaliação, e vice-versa.
- Só as referências ficam acessíveis em L3. As realizações de avaliação não estimam o nulo do mesmo caso.

## 5. Blocos temporais e controles nulos (§9.3)

- A repetição `r` vai para o bloco `r × blocos ÷ repetições`: com 10 repetições e 10 blocos, o bloco `r` contém a
  repetição `r` de todas as unidades.
- Dentro de cada bloco, a ordem é embaralhada com semente. Cada chamada do pipeline vem depois da sua tradução.
- O runner espera pelo menos `block_spacing_s` entre os inícios de blocos consecutivos. O início de cada bloco fica
  registrado, e a retomada não espera de novo por um bloco já iniciado.
- **Interpretação declarada.** O piloto não tem intervenção deliberada: mede a variabilidade sob condições
  observáveis fixas. Toda repetição de uma condição com entrada fixa é, portanto, um controle nulo. O ACM isolado,
  com entrada idêntica em todas as chamadas, é o controle nulo por excelência.
- `check_schedule` exige que **todo bloco contenha as três condições e as duas funções**. Assim nem todas as
  referências caem num dia e todas as avaliações noutro. Uma semente que viole isso é recusada, não sorteada de novo
  em silêncio.
- Uma mudança de `ModelVersion` retornada inicia um novo estrato na comparação e não se mistura ao nulo da mesma
  versão. Versão igual não prova ausência de alteração interna.

## 6. O que é registrado (§6.5)

Por tentativa, há uma atividade PROV com identificador próprio (`urn:uuid:`), distinto do hash de conteúdo. Ela
registra:

- estado (`ok`/`error`), início e fim, endpoint e região;
- modelo retornado (`ModelVersion` no ACM; id do modelo no Bedrock);
- configuração efetiva (operação, parâmetros, perfil, temperatura, `max_tokens`);
- código (pacote, módulo, commit git e se o repositório estava sujo) e versões de habench, boto3 e botocore;
- erro (tipo, código, mensagem, se é repetível);
- consumo (caracteres, unidades, tokens, latência medida e latência informada pelo serviço, custo reservado e
  conciliado com a base do cálculo);
- RequestId, data HTTP e status HTTP.

Entidades e relações:

- **Entrada efetiva:** entidade com sha256. No pipeline completo, o texto ACM é salvo em arquivo e ligado à saída da
  tradução por `wasDerivedFrom`.
- **Saída:** o corpo HTTP bruto exato (`raw/<tentativa>.body`), o dicionário da resposta como o HealDB o guardava
  (`raw/<tentativa>.json`, com `ResponseMetadata`) e o texto traduzido (`outputs/<tentativa>.txt`).
- **Relações:** `used`, `wasGeneratedBy`, `wasAssociatedWith` (agente: o runner, com versões) e `wasInformedBy`
  (retentativa → tentativa anterior; ACM do pipeline → tradução).
- Credenciais e cabeçalhos de autenticação nunca são gravados. Registros passam por limpeza e verificação. Corpos
  brutos, respostas, traduções e entradas do pipeline são verificados antes da gravação. Um arquivo com padrão de
  credencial não é gravado, e a recusa fica registrada na entidade (`body_refused`, `json_refused`, …). Uma chamada
  do pipeline cuja entrada não pôde ser gravada não é executada.
- O número de tentativas por chamada nunca passa de `retry.max_attempts`, mesmo quando uma tentativa foi
  interrompida.
- Falha nunca vira resposta vazia. Uma chamada cuja tradução-mãe falhou fica registrada como `not_executed`, e não
  como ausência de associações.

## 7. Comparação (§5.2)

- **Nível 1:** sha256 do corpo HTTP bruto.
- **Nível 2:** JSON canônico da resposta sem **apenas** o `ResponseMetadata` de nível superior, com as chaves
  ordenadas e a ordem dos arrays preservada.
- Comparação por (condição, texto[, perfil]) e por `ModelVersion`.
- **Traduções:** igualdade exata, igualdade com espaços normalizados e distância de edição por caracteres.
- Falhas são contadas à parte, nunca como conteúdo distinto.

## 8. Comandos

```
uv run python -m habench.campaign plan-smoke --plan PLANO.yaml --out smoke.json
uv run python -m habench.campaign plan-pilot --plan PLANO.yaml --out piloto.json
uv run python -m habench.campaign estimate  --plan PLANO.yaml --schedule piloto.json
uv run python -m habench.campaign run       --plan PLANO.yaml --schedule piloto.json --run-id ID   # simulação
uv run python -m habench.campaign status    --run-id ID
uv run python -m habench.campaign compare   --run-id ID --out comparacao.json
```

A execução paga acrescenta `--paid --budget-usd X` com `HAB_PAID_CALLS=1`. Só a sessão principal a faz.

## 9. Decisão após o piloto (§9.5)

Se não houver variação relevante no desfecho, registra-se o resultado com seu limite de detecção. H2 não é declarada
confirmada nem refutada. A campanha de teste (150 × 5) não está autorizada (`docs/decisoes.md`).
