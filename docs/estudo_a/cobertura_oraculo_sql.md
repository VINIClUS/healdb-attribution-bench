| Fator | Nível | Oráculo SQL histórico | Observação |
|---|---|---|---|
| `occ` | `last_upsert` | fixo | comportamento do código 405a10c; é o nível de todas as células do oráculo |
| `occ` | `per_entity_any` | não | o código histórico só implementa o upsert com última ocorrência |
| `occ` | `first_upsert` | não | o código histórico só implementa o upsert com última ocorrência |
| `sel` | `all` | fixo | comportamento do código 405a10c; é o nível de todas as células do oráculo |
| `sel` | `top1` | não | o código histórico não seleciona o conceito de maior escore por entidade |
| `ent_thr` | `0.6` | sim (405a10c ajustável) | constante de `vl_entity_score >= t` na linha 141; SQL do HEAD (3 parâmetros) é oráculo possível sob o preset V2: catalogado, não executado |
| `ent_thr` | `0.7` | sim (405a10c ajustável) | constante de `vl_entity_score >= t` na linha 141; SQL do HEAD (3 parâmetros) é oráculo possível sob o preset V2: catalogado, não executado |
| `ent_thr` | `0.55` | sim (405a10c ajustável) | constante de `vl_entity_score >= t` na linha 141; SQL do HEAD (3 parâmetros) é oráculo possível sob o preset V2: catalogado, não executado |
| `ent_thr` | `0.65` | sim (405a10c ajustável) | constante de `vl_entity_score >= t` na linha 141; SQL do HEAD (3 parâmetros) é oráculo possível sob o preset V2: catalogado, não executado |
| `icd_thr` | `0.6` | sim (405a10c ajustável) | constante de `vl_score >= t` na linha 141; SQL do HEAD (3 parâmetros) é oráculo possível sob o preset V2: catalogado, não executado |
| `icd_thr` | `0.3` | sim (405a10c ajustável) | constante de `vl_score >= t` na linha 141; SQL do HEAD (3 parâmetros) é oráculo possível sob o preset V2: catalogado, não executado |
| `icd_thr` | `0.55` | sim (405a10c ajustável) | constante de `vl_score >= t` na linha 141; SQL do HEAD (3 parâmetros) é oráculo possível sob o preset V2: catalogado, não executado |
| `icd_thr` | `0.65` | sim (405a10c ajustável) | constante de `vl_score >= t` na linha 141; SQL do HEAD (3 parâmetros) é oráculo possível sob o preset V2: catalogado, não executado |
| `trait` | `v1` | sim (405a10c ajustável) | conjuntos e regra HYPOTHETICAL nas linhas 135-148 |
| `trait` | `v2` | não | exige o Type da entidade, que link@405a10c não seleciona |
| `trait` | `v1_hyp_le_0.6` | sim (405a10c ajustável) | conjuntos e regra HYPOTHETICAL nas linhas 135-148 |
| `trait` | `v1_no_required` | sim (405a10c ajustável) | conjuntos e regra HYPOTHETICAL nas linhas 135-148 |
| `trait` | `neg_only` | sim (405a10c ajustável) | conjuntos e regra HYPOTHETICAL nas linhas 135-148 |
| `map` | `cm_gated` | sim (405a10c ajustável) | bloco do portão (linhas 110-132) removido para cm_ungated; `search_repository_icd` inalterada |
| `map` | `cm_ungated` | sim (405a10c ajustável) | bloco do portão (linhas 110-132) removido para cm_ungated; `search_repository_icd` inalterada |
| `map` | `who_exact_fb` | não | projeção para a OMS (who_*) não existe no código histórico |
| `map` | `who_exact` | não | projeção para a OMS (who_*) não existe no código histórico |
| `map` | `who_cat3` | não | projeção para a OMS (who_*) não existe no código histórico |
| `dup_ind` | `True` | não | contrafactual indisponível: não há resposta ACM armazenada para a entrada alterada |
| `dup_ind` | `False` | não | contrafactual indisponível: não há resposta ACM armazenada para a entrada alterada |
| `mask_drug` | `False` | não | contrafactual indisponível: não há resposta ACM armazenada para a entrada alterada |
| `mask_drug` | `True` | não | contrafactual indisponível: não há resposta ACM armazenada para a entrada alterada |
| `wow_rewrite` | `False` | não | contrafactual indisponível: não há resposta ACM armazenada para a entrada alterada |
| `wow_rewrite` | `True` | não | contrafactual indisponível: não há resposta ACM armazenada para a entrada alterada |
| `cut10k` | `True` | não | contrafactual indisponível: não há resposta ACM armazenada para a entrada alterada |
| `cut10k` | `False` | não | contrafactual indisponível: não há resposta ACM armazenada para a entrada alterada |
| `translation` | `stored` | não | contrafactual indisponível: não há resposta ACM armazenada para a entrada alterada |
| `acm_model` | `stored` | não | contrafactual indisponível: não há resposta ACM armazenada para a entrada alterada |
| `patch:<id>` | `True` | não | edição semissintética: nenhuma execução histórica corresponde a ela |
