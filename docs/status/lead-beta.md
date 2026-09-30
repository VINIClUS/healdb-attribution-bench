GATE2: ready for review

# Status — Lead β

## Estado

β1 e β2 concluídos e commitados; parado na GATE 2 (β3 não iniciado).

## Feito

- β1: `docs/analise/00_analise_protocolo.md`: 38 citações verificadas, 21 checagens internas, lacunas com
  resoluções R01–R30, achados E01–E17 (a re-derivar), ameaças à validade e 12 emendas.
- β2: `docs/SPEC.md` v0.1, com 23 exemplos semânticos (EX-01…EX-23) e 35 de pontuação (EX-S01…EX-S35). Cobre todos
  os itens da lista β2 do brief.
- `tests/data/spec_examples.json` e `tests/test_spec_examples.py`.
  - O teste tem uma referência de força bruta que não importa `habench` (só o teste de vocabulário importa
    `habench.types`).
  - Confere que os ids `EX-` do SPEC e do JSON são os mesmos, nos dois sentidos, e que a tabela de pontuação é total.
  - Um hab-worker escreveu o teste a partir só do SPEC e do esquema do JSON. Eu escrevi os valores esperados. Todos
    conferiram de primeira, então o SPEC foi preciso o bastante para uma implementação independente.
  - Revisei o teste. Corrigi `backing_check`, que não conferia certificados `dummy` contra a tabela-verdade, e
    acrescentei o caso EX-21 (d).
- Checagem cruzada: todo R-id da análise aparece no SPEC. R24 é declarado fora do escopo do SPEC (Q3).

## Em andamento

(nada)

## Próximo

- Após aprovação da GATE 1 e da GATE 2: β3 (`oracle/*`, `eval/*`).

## Testes

- `uv run pytest tests/test_spec_examples.py -q` → `62 passed`
- `uv run pytest -q` (após `git merge main`) → `488 passed`

## Números re-derivados

| valor | comando | arquivo |
|---|---|---|
| SHA-256 `bd466b36…d1f4`, 33.897 bytes | `sha256sum`; `os.path.getsize` via `uv run python` | `/home/vinicius/code/HealDB/doc/PROVENIENCIA_NLP_V1.md` (F1) |
| SHA-256 `856d5c31…d515`, 21.480 bytes | idem | `/home/vinicius/code/HealDB/doc/RECONSTRUCAO_V1_MATRIZ.md` (F2) |
| SHA-256 `822750b7…a4ff` | `uv run python -c "import hashlib;..."` | `/home/vinicius/Downloads/Esboco_revisado_HealDB_IC_Unicamp(2).pdf` (F3) |
| SHA-256 `7bfed6c0…a34c` | `sha256sum` | `docs/protocolo/Protocolo_Experimental_HealDB_Revisado_v0_2.md` |

Todos são iguais a `docs/protocolo/SHA256SUMS` e, para F1/F2, aos hashes e tamanhos citados no protocolo. Os números de
`docs/design/` citados na análise estão marcados "a re-derivar" e não foram recomputados por mim.

## Perguntas / BLOCKED

Nenhum BLOCKED. Decisões marcadas **[revisar]** para a GATE 2:
1. **R09.** O contraste primário de H1a usa o regime de orçamento suficiente (b = 64). As curvas de 16 e 32 são
   secundárias. Nesse regime a não inferioridade tende a ser quase automática; a alternativa é b = 32 como primário.
2. **R17.** Estimando de H1b: dois estratos da família I, divergência (L2-R × L2-R−A3, R-A) e perda de replay (L2-M ×
   L2-R, R-C), com guarda de risco de +2 pp.
3. **§4.3 do SPEC.** O espaço de variantes K e as hipóteses de divergência de nível definem o universo de
   identificação em R-C e sem vínculo ao código. É uma escolha de modelagem minha: sob R-C, a implementação do nível
   executado é incerta dentro de K.
4. **R13.** A cobertura primária usa só as consultas alteradas. As inalteradas alimentam as métricas de controle
   nulo.

## Desvios propostos

- **P-β1 (níveis queimados).** `docs/design/desenho_inicial.md` §C nomeia candidatos a níveis de teste. Proposta:
  tratar todo valor citado em `docs/design/` ou em `docs/SPEC.md` como queimado e excluí-lo da lista selada (R28). O
  SPEC não repete os valores do desenho.
- **P-β2 (H2 não confirmatória nesta fase).** A campanha de teste não está autorizada, então o terceiro contraste
  primário entra no Holm com p = 1 e o piloto dev/cal é exploratório (R15, R18).
- **P-β3 (citações).** Corrigir as seções citadas em §1.1 (C08, C09) e a fonte de §4.1 (C23) na versão confirmatória.
- **P-β4 (anotação).** Os 20 textos do piloto de anotação saem de dev/cal (R24; afeta o lead δ).

## REQUEST

(nenhum)
