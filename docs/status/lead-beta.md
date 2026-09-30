GATE2: revised (v0.2)

# Status — Lead β

## Estado

β1 concluído. β2 revisado para o SPEC v0.2 conforme o veredito da GATE 2 ("aprovar com correções"). Parado para a
reconferência da sessão principal; β3 não iniciado.

## Feito

- β1: `docs/analise/00_analise_protocolo.md`: 38 citações verificadas, 21 checagens internas, lacunas com
  resoluções R01–R30, achados E01–E17 (a re-derivar), ameaças à validade e 12 emendas.
- β2 v0.1: `docs/SPEC.md`, com os exemplos EX-01…EX-23 e EX-S01…EX-S35.
- **β2 v0.2 (GATE 2).**
  - `git merge main`. Li a auditoria (A01–A21), `docs/decisoes.md` ("GATE 2") e `docs/deviations.md` D7.1–D7.10.
  - `docs/SPEC.md` v0.2 aplica A01, A02, A03, A09, A13 e A14, mais A04, A05, A06, A07, A08, A10, A11, A12, A18, A20
    e A21. O §16 traz o changelog, uma linha por A-id.
  - A semântica do núcleo segue `pipeline/core.py`, citado linha a linha.
    - `top1` é sempre por grupo de `Id`: último candidato por código, depois colação MySQL. Os vencedores saem na
      ordem da primeira aparição do grupo de `Id`, não na ordem de emissão (EX-29), e isso muda `last_upsert` e
      `first_upsert`.
    - Em `per_entity_any`, os traços vêm de todas as entidades do `Id`.
    - Nos níveis `who_*`, um código sem projeção reprova em `map` e não vira `unmapped` (corrigi o §1.2 da v0.1).
  - Exemplos novos:
    - EX-24 (`h* ∉ U` → `indeterminado`);
    - EX-25 e EX-26 (`Id` duplicado);
    - EX-29 (ordem de saída de `top1`) e EX-30 (contraexemplo da regra 2 sem a condição de ordem);
    - EX-27 (`who_exact_fb → who_exact`);
    - EX-28 (a/b, BFS com inadmissíveis);
    - EX-21 (e)–(h) (eval fora do log, trace de L2-R sem avaliação no log, e R-C);
    - EX-S36 (certificado falso em `ambiguo`);
    - EX-S37…EX-S53 (as linhas célula × estado que faltavam, mais a necessidade 0 em R-C).
  - EX-15 agora certifica `trait`. EX-19 foi recalculado com α = 0,025: 0,0880973.
  - A referência de `tests/test_spec_examples.py` foi atualizada. Continua sem importar `habench`: só **dois** testes
    de vocabulário importam `habench.types`.
    - Implementa as regras dummy 0–5.
    - A completude da BFS verifica os inadmissíveis pulados.
    - O lastro faz o passo 0: aceitação por tipo, log e célula.
    - `W` é calculado sobre `U ∪ {h*}`, com o estado de identificação.
    - O risco comprometido está implementado.
  - Teste novo `test_dummy_rules_are_sound_on_random_contrasts`: 4.800 contrastes aleatórios com `Id` duplicado e
    patches (600 livres, 600 com cada fator forçado em `D`, e 600 dirigidos à ordem de `top1`); nenhum certificado de
    referência é falso.
    - O gerador dirigido acha o contraexemplo da regra 2 sem a condição de ordem.
    - Uma sonda avulsa com 51.000 contrastes deu 0 falsos em 41.689 certificados.

## Em andamento

(nada)

## Próximo

- Após a reconferência da GATE 2: β3 (`oracle/*`, `eval/*`), incluindo as medições de A15 e os testes diferenciais
  de A19.

## Testes

- `uv run pytest tests/test_spec_examples.py -q` → `88 passed`
- `uv run pytest -q` → `514 passed`

## Números re-derivados

| valor | comando | arquivo |
|---|---|---|
| SHA-256 `bd466b36…d1f4`, 33.897 bytes | `sha256sum`; `os.path.getsize` via `uv run python` | `/home/vinicius/code/HealDB/doc/PROVENIENCIA_NLP_V1.md` (F1) |
| SHA-256 `856d5c31…d515`, 21.480 bytes | idem | `/home/vinicius/code/HealDB/doc/RECONSTRUCAO_V1_MATRIZ.md` (F2) |
| SHA-256 `822750b7…a4ff` | `uv run python -c "import hashlib;..."` | `/home/vinicius/Downloads/Esboco_revisado_HealDB_IC_Unicamp(2).pdf` (F3) |
| SHA-256 `7bfed6c0…a34c` | `sha256sum` | `docs/protocolo/Protocolo_Experimental_HealDB_Revisado_v0_2.md` |
| `1 − 0,025^{1/40}` = 0,0880973 (EX-19) | `uv run python` | – |

## Perguntas / BLOCKED

Nenhum BLOCKED. Os itens **[revisar]** da v0.1 foram decididos na GATE 2 e estão aplicados.

## Desvios propostos

P-β1 a P-β4 foram registrados pela sessão principal como D7.5, D7.3 e D7.6. P-β3 (corrigir as citações em §1.1 e §4.1
na versão confirmatória) continua como proposta.

## REQUEST (lead α)

Regras dummy de `pipeline/semantics.dummy` que mudaram da v0.1 para a v0.2 (SPEC §4.6):

| regra | v0.1 | v0.2 |
|---|---|---|
| 1, limiar | só a evidência sem patches | aplicada a todo subconjunto dos patches de `D` que editam `a.med` (vale para todas as regras) |
| 2, `sel` | todo candidato relevante tem `rank` 1 na sua entidade | todo candidato relevante é o mantido por `top1` no seu **grupo de `Id`** (3.2 passo 3) **e**, por código, os candidatos relevantes têm a mesma ordem relativa na emissão e na saída de `top1` |
| 3, `occ` | códigos únicos e uma entidade por código | códigos únicos, `Id` únicos, e cada `Id` com uma **única** entidade |
| 4, `map` | só `cm_gated` × `who_exact_fb` no espaço OMS | generalizada: para todo código, "passa no portão e projeta para a chave de `a`" igual nos dois níveis |
| 0, triviais | – | nova: `f ∉ D`, `UNAVAILABLE`, patch que não edita `a.med` |
| 5, `trait` | – | nova: enumeração dos subconjuntos do pool de entidades; mais de 10 entidades → `None` |

Pela leitura do código, `semantics.dummy` já implementa as regras 0, 1, 3, 4 e 5. Pedidos:
1. **Defeito na regra 2** (`semantics.py:126-129`). Ela só testa a pertinência a `core._select(v, "top1")`. Falta a
   condição de ordem. Em EX-30 ela certifica `sel`, mas `C61` vai de ausente a presente.
2. **Docstring de `_select`** (`core.py:100`). Ela diz "in emission order", mas o código devolve os vencedores na
   ordem da primeira aparição do grupo de `Id`. Pela decisão da GATE 2, o código é normativo e o SPEC o descreve (3.2
   passo 3). Se α mudar o comportamento em vez da docstring, o SPEC acompanha.
3. Um teste de solidez por propriedade (hypothesis) contra força bruta, com `Id` duplicado e códigos repetidos entre
   grupos. `random_sel_contrast` e `test_dummy_rules_are_sound_on_random_contrasts` servem de modelo.
