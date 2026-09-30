# Replay Docker de 405a10c e validação cruzada SQL

Reexecuta `process_disease_data_json` e `link_medications_with_diseases` de 405a10c (blobs `02d294c` e `c9c4aeb`)
sobre o dump V1 em MySQL 8.0.33 e, depois, roda ~100 variantes do `link` (constantes alteradas por substituição
textual exata, ver `src/habench/historical/xval.py`) em medicamentos de desenvolvimento apenas. Nada aqui usa AWS
ou rede externa. A senha vem só de `HAB_MYSQL_PASSWORD` (nunca é escrita em arquivo, log ou linha de comando).

Nomes: contêineres `healdb-replay-mysql` e `healdb-replay-py`, volume `healdb-replay-mysql-data`, rede
`healdb-replay-net`. Saídas em `/home/vinicius/hab-data/replay/{logs,export,code,xval}`.

## Comandos (na raiz do repositório, nesta ordem)

```
export HAB_MYSQL_PASSWORD='<senha descartável escolhida pela sessão principal>'
bash scripts/replay/up.sh
bash scripts/replay/replay_405a10c.sh
bash scripts/replay/xval.sh
unset HAB_MYSQL_PASSWORD
```

Depois, offline (o lead): `uv run python -m habench.historical.xval compare` e a escrita de
`repro/replay_manifest.json` (`habench.historical.replay.write_replay_manifest`). Para limpar:
`bash scripts/replay/down.sh` (remove apenas `healdb-replay-*`).

## Tempo estimado

- `up.sh`: carga ~1 min (api_response de 150 MB domina).
- `replay_405a10c.sh`: process ~546 s, link ~148 s, exportação de TSVs poucos segundos (~12 min no total).
- `xval.sh`: ~148 s x (1.082/7.447) ~ 21,5 s por configuração x 100 ~ 36 min, mais a cópia dev-only.

## O que devolver

Nada sai da máquina; informe ao lead: o resultado final de cada script (linhas `LOAD_DONE`, `driver rc=`,
`xval driver rc=`), e confirme que existem em `/home/vinicius/hab-data/replay/`:
`logs/{images.txt,pip_freeze.txt,blobs.txt,commands.log,up.log,up.err,replay_405a10c.log,xval.log}`,
`export/{entity,trait,md}.tsv`, `export/export_meta.json`, `xval/*.tsv`, `xval/configs.json`.
Se algum script falhar, envie as últimas 30 linhas do log correspondente (sem a senha, que nunca é registrada).
