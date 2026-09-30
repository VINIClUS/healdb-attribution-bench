# healdb-attribution-bench

Implementação do protocolo experimental revisado do HealDB (v0.2): atribuição de mudanças por associação medicamento–doença sob proveniência parcial e reexecução limitada.

- Protocolo: `docs/protocolo/Protocolo_Experimental_HealDB_Revisado_v0_2.md` (hash em `docs/protocolo/SHA256SUMS`)
- Decisões e desvios: `docs/decisoes.md`, `docs/deviations.md`
- Regras para sessões e agentes: `CLAUDE.md`

Uso básico:

```
uv sync
uv run pytest                 # exclui docker e paid
uv run pytest -m dumps        # requer HAB_DUMPS_DIR / HAB_DATA_DIR
```
