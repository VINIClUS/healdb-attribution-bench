# Lead δ — status

## Estado
δ1, δ2 e δ3 concluídos sobre fixtures. Nenhuma chamada paga feita. Aguarda o manifesto e os snapshots do lead α para
gerar os cronogramas reais.

## Feito
- **δ1 `prov/`** (commit `01a9288`):
  - registros PROV-DM (Entity/Activity/Agent/Relation, 5 relações);
  - id por tentativa (`urn:uuid`), sempre distinto do sha256;
  - store JSONL com flock e round-trip;
  - export PROV-JSON sem dependência;
  - limpeza de credenciais (chaves, valores, camelCase);
  - ledger de afirmações com `ClaimState` e regras de evidência/limites.
- **δ2 `campaign/`**:
  - `plan.py`, `calls.py`, `repro/campaign_plan.template.yaml`: contratos, preços no plano, ids de modelo como
    marcadores (commit `204987f`).
  - `money.py` (lead) (commit `204987f`):
    - guarda com 4 condições;
    - ledger cumulativo com flock;
    - reserva do pior caso por tentativa e recusa sem escrita;
    - órfãs contam como gasto;
    - falha conciliada pelo pior caso;
    - teto do plano e orçamento da execução.
  - `compare.py` (níveis 1 e 2, estratos por `ModelVersion`, traduções exata/normalizada/edição) e `estimator.py`
    (commit `204987f`).
  - `acm.py`, `translate.py`, `aws.py` (commit `421a962`):
    - `total_max_attempts=1`, provado em loopback (1 requisição HTTP por chamada);
    - corpo bruto exato;
    - boto3 importado só sob demanda.
  - `schedule.py`, `texts.py` (commit `9829387`):
    - smoke 20 × 5 (dev);
    - piloto de 60 textos estratificados de dev ∪ cal, 3 condições, funções 6/4 herdadas pelo pipeline, blocos
      temporais;
    - `SealedError` para teste;
    - log de elegibilidade.
  - `runner.py` (lead), `cli.py`, `__main__.py`, `docs/campanha/protocolo_campanha.md` (commit `64d2d03`):
    - retomável, com lock de execução, espera entre blocos;
    - uma reserva e uma atividade PROV por tentativa;
    - verificação de credenciais antes de gravar qualquer arquivo;
    - teto de tentativas também após interrupção.
  - Os testes adversariais do runner (worker independente) acharam 3 bugs, corrigidos:
    1. tentativa extra após interrupção;
    2. `SecretLeak` não tratado na resposta;
    3. textos gravados sem verificação.
- **δ3 `annotation/`** (commit `0e309e2`):
  - amostrador em duas fases (130 estratificados, π1 = n_h/N_h; 50 duplos, π2 = 50/130), piloto disjunto;
  - planilha cega sem estrato, saídas, ids ou pesos;
  - kappa por categoria (None se p_e = 1) e alfa de Krippendorff nominal, validado contra força bruta;
  - adjudicação explícita;
  - guia `repro/annotation_guide.md`.

## Em andamento
- Nada.

## Próximo (sessão principal)
- Quando existirem `repro/split_manifest.csv` e os snapshots V2: rodar `plan-smoke` e `plan-pilot`, depois
  `estimate`; preencher os ids de modelo Bedrock e os preços numa cópia do template; rodar a simulação. A execução
  paga é da sessão principal: `HAB_PAID_CALLS=1 … run --paid --budget-usd X`.

## Testes
- `uv run pytest -q` → `255 passed, 3 warnings in 7.99s`. Os avisos são o `DeprecationWarning` de fork dos testes
  de concorrência do ledger e do store.

## Números re-derivados
- Fórmulas do §13, testadas em `tests/test_campaign_estimator.py` (`uv run pytest tests/test_campaign_estimator.py`):
  - 150 × 3 × 5 = 2.250 traduções;
  - 60 × 3 × 10 = 1.800 traduções;
  - chamadas ACM do piloto: 600 + 1.800 = 2.400.
- Contagens do cronograma do piloto (60 textos, 3 perfis, 10 repetições): 600 ACM isolado, 1.800 traduções,
  1.800 ACM do pipeline. Teste em `tests/test_campaign_schedule.py`.
- Custos em US$ ainda não calculados: dependem dos textos reais e dos preços Bedrock.

## Perguntas / BLOCKED
- (nenhuma)

## Desvios propostos
- **Retentativas do botocore.** O brief diz `max_attempts=1`, mas no botocore `max_attempts` conta só as
  retentativas. Usei `total_max_attempts=1` (exatamente uma requisição HTTP), que realiza a intenção do brief.
- **Controles nulos (§9.3).** O piloto não tem intervenção; toda repetição com entrada fixa é nulo. Exige-se que
  todo bloco tenha as 3 condições e as 2 funções (`protocolo_campanha.md` §5).
- **Pipeline completo.** Sem mascaramento `<drug>` (o brief pede isso; o mascaramento da V2 não é reproduzível a
  partir do código comitado).
- **Falhas.**
  - Custo conciliado pelo pior caso: não se sabe se a AWS cobra falhas.
  - Se a tradução-mãe falhou ou não pôde ser gravada, a chamada do pipeline fica `not_executed`, nunca como
    ausência.
- **Um estrato com poucos grupos elegíveis** faz o piloto falhar com erro, em vez de redistribuir a vaga entre os
  outros estratos. Revisar quando houver dados reais.

## REQUEST
- **Dependência de lead-alpha.** Faltam `repro/split_manifest.csv` e os snapshots parquet V2:
  - `snapshots/v2/api_response.parquet`, colunas `id_medication`, `ds_text_submitted`;
  - `snapshots/v2/translate_eng_leaflet_section.parquet`, colunas `id_medication`, `ds_indication`.

  Os nomes assumidos estão em `campaign/texts.py`.
- **`.gitignore`.** O padrão `data/` ignora `tests/data/`. O fixture sintético `tests/data/campaign/split_manifest.csv`
  foi adicionado com `git add -f`. Sugiro `!tests/data/` no `.gitignore` (arquivo da sessão principal).
- **Plano de campanha.** A sessão principal deve fixar os ids de modelo Bedrock e os preços por MTok numa cópia de
  `repro/campaign_plan.template.yaml` antes de qualquer execução paga.
