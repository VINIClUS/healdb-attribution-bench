# Desenho inicial (agente Plan)

> Relatório de subagente (Sonnet) produzido em 2026-09-30 na sessão de planejamento, somente leitura.
> Números aqui são de rascunho: re-derivar em código versionado antes de citar em relatório.
> Onde se lê ThesisBench/thesisbench, leia healdb-attribution-bench/habench.

# ThesisBench design: implementable spec, oracle, identification reference, methods, tests, work breakdown

## 0. What I measured while planning

All checks were read-only, in memory, in pure Python over the dumps.

- **Toolchain.** uv 0.12.4 has CPython 3.12.13 installed. The system `python3` is 3.14.4, so commit `.python-version` = 3.12. Docker has `mysql:8.0.33` and `python:3.12-slim`. The machine has 8 cores and 15 GB. PyPI reachability is unverified, so make `uv sync` the first smoke test. `/home/vinicius/code/ThesisBench` holds an untracked `ic-tese-v3-2026.07.29.zip` (thesis template); keep it out of commits.
- **V1 fidelity.** A parameterized function of about 50 lines over the parsed JSON (array order kept) gives 0 diffs against V1 `entity` (274,010), `trait` (469,957) and `md` (43,194), with the exact funnel. It runs in about 25 s, with no MySQL.
- **V2 fidelity.** The same approach gives 0 diffs against V2 `entity_icd` (375,595), `entity_trait` (107,543), `cutoff_audit` (75,119) and `md` presence (27,861), in about 20 s. There are no GROUP_CONCAT ties in the data.
- **Two presets, one function.** One switchable function reproduces both. V1 `md` projected to WHO gives 34,101 keys and V2 `md` gives 27,861, both with 0 diffs.
- **The 1-ULP `entity` value.** Python parses the dump's decimal text, so the value matches. The ULP appears only when MySQL re-parses the JSON. Whitelist it in SQL-replay tests.
- **Real V1-vs-V2 contrast on the V1 responses.**
  - 64 hybrids over all 7,447 responses take 41 s.
  - 45,689 associations change (27,405 appear, 18,284 disappear).
  - Minimal-family shapes: 27,874 single-set, 14,182 two-set, 3,464 three-set, 169 with 4–5 sets. 4,555 (10%) are non-monotone.
  - Factor participation in some minimal set: `sel` 23,425, `occ` 18,859, `trait` 17,561, `icd` 12,784, `ent` 2,287, `map` 0. The V1 hierarchy gate and V2's NO_MAP drop are the same predicate, so `map` is a natural no-effect factor in WHO space.
  - Among 141,662 associations there are only 804 distinct truth tables (5 effective factors). With endpoint-only evidence, 45 different families co-occur for appearing associations.
- **ACM is deterministic inside a run.** 0 of 1,554 pairs differ in V1 (197 EN-identical groups) and 0 of 1,937 in V2 (319 groups). The one-sided 95% upper bound on the differing-group fraction is about 1.5% and 0.9%. H2/L3 therefore cannot be exercised on historical data. Only Study C or a declared simulator (mechanism tests only) can.
- **Data invariants.**
  - Concept lists have length 0 or 5, sorted descending, with no top ties.
  - Array order differs from `Id` order in every non-empty response, and from `BeginOffset` order in 1,600.
  - 71 V2 responses repeat an entity `Id`, and V2's upsert merges them.
  - 1,460 TIME_TO_DX_NAME entities have no concepts, so V2's DX_NAME filter is a no-op.
  - No score equals 0.60 exactly, so boundary cases need flagged edits.
  - 6.2% of entity scores and 12.6% of concept scores lie in [0.55, 0.65).
- **BugDoc exists.** VIDA-NYU/BugDoc, BSD-3, commit `75e3d26`. Only `StackedShortcutStandalone` runs in-process; the other algorithms need ZMQ.
- **Dev partition size.** `extend_amostra.csv` alone spans 278 medications, so dev exceeds 200 texts. Log this in `deviations.md`.

## A. Layout and core signatures

```
ThesisBench/  pyproject.toml, .python-version, docs/SPEC.md, repro/ (§15.1 files), third_party/bugdoc/ (vendored, pinned)
 src/thesisbench/
  types.py     AssocKey, Presence, Family, ClaimState, Claim
  data/        dumps.py (clean-room port of dumprows; never db_utils), store.py, groups.py, splits.py, sampling.py
  pipeline/    catalog.py evidence.py core.py trace.py mapping.py semantics.py equality.py tables_v1.py tables_v2.py
  oracle/      hybrids.py families.py truth.py universe.py identify.py
  scenarios/   generate.py edits.py contrasts.py catalog.yaml
  views/       layout.py profiles.py build.py ids.py isolation.py
  env/         api.py broker.py meter.py
  methods/     base.py b0.py b1.py b2.py b3.py m.py search.py bugdoc_adapter.py
  eval/        score.py metrics.py stats.py precision_sim.py
  prov/  campaign/  annotation/  historical/  runner/
 tests/ (markers: dumps, docker, slow, paid).  Gitignored: data/ truth/ views/ runs/
```

```python
Family = frozenset[frozenset[str]]                          # antichain of factor sets
@dataclass(frozen=True, slots=True, order=True)
class AssocKey: med: int; system: str; version: str; code: str   # ("ICD-10-CM","acm:<ModelVersion>") | ("ICD-10-WHO","hier:<sha256>")
class Presence(StrEnum): PRESENT; ABSENT; UNAVAILABLE       # failed or missing response is never ABSENT
@dataclass(frozen=True) class Factor: name; stage: Literal["prep","acm","post","patch"]; levels: tuple
@dataclass(frozen=True) class Config: items: tuple[tuple[str, Level], ...]; def with_(**kw); def diff(o) -> frozenset[str]
def hybrid(x0: Config, x1: Config, S: frozenset[str]) -> Config
def run(cfg, ev: GroupEvidence, hier, space: KeySpace, *, trace=False) -> RunResult   # state, attrs, status per med, Trace|None
# Trace: CandRow(cid, med, pos, eid, code, rank, es, cs, tp, traits); RecordRow(key, members, es, cs, trait_union); Decision(ref, stage, verdict, reason)
def hybrid_table(x0, x1, ev, hier, space, avail=lambda S: True) -> HybridTable      # 2^|D| runs, |D| <= 6
def minimal_family(tab, a) -> Family;  def analyze(tab, a) -> CaseTruth
def identify(truth, tab, a, vk: ViewKey, uni: Universe) -> Ident                    # W_lo ⊆ W_hi, saturated, n_hist
class Env(Protocol):
    cap: str
    def artifacts(self) -> Sequence[ArtifactRef]; def read(self, ref) -> bytes
    def contrast(self) -> tuple[str, str]; def config(self, run) -> Config; def final(self, run) -> Mapping[AssocKey, Presence]
    def evaluate(self, apply: frozenset[str]) -> EvalResult     # 1 unit per distinct S; cached; raises Unavailable / BudgetExhausted
    def meter(self) -> Meter                                    # evals, bytes, cpu, rss; raw and amortized
class Method(Protocol):
    name: str
    def explain(self, env, queries: Sequence[Query]) -> Mapping[str, Explanation]      # one budget per contrast
@dataclass(frozen=True) class Explanation: qid; state: State; families: frozenset[Family]; certificates; claims; reason; confidence
def score(expl, truth, ident, evallog) -> Scored;  def aggregate(scored, by) -> Metrics
```

## B. Specifications

### B1. Factor catalog

| factor | stage | x0 (V1) → x1 (V2) | other levels | semantics and dummy test |
|---|---|---|---|---|
| `occ` | post | `last_upsert` → `per_entity_any` | `first_upsert` | V1: key is (med, CM code), scores from the last candidate, traits unioned. V2: key is ACM entity `Id`, each decided alone, presence = any, score = MAX. Dummy when the key has a single candidate. |
| `sel` | post | `all` → `top1` | – | Keep the rank-1 concept per entity (score desc, code asc) before `occ`. |
| `ent_thr` | post | 0.60 → 0.70 | 0.55, 0.65 | es ≥ t. Dummy iff no relevant score lies in [min, max). |
| `icd_thr` | post | 0.60 → 0.30 | 0.55, 0.65 | cs ≥ t (V2's MAX ≥ t is equivalent to any). |
| `trait` | post | `v1` → `v2` | `v1_hyp_le_0.6`, `v1_no_required`, `neg_only` | Veto set, HYPOTHETICAL rule, required DX/SYM/SIGN, DX_NAME. |
| `map` | post | `cm_gated` → `who_exact_fb` | `cm_ungated` (extend), `who_exact`, `who_cat3` | Gate plus projection and key space. |

Other catalog entries:
- `patch:<id>` factors apply a semisynthetic evidence edit.
- Prep and ACM factors (`dup_ind`, `mask_drug`, `wow_rewrite`, `cut10k`, `translation`) are catalogued as `stage=prep`. They have no hybrid unless a stored response exists.
- Attribute knobs (`low_conf_thr`, `icd_hi`) never enter D for presence targets.

Bundles: `V1_TO_V2 = (occ, sel, ent_thr, icd_thr, trait, map)` (|D| = 6), and `EXTEND = (map: cm_gated → cm_ungated)`.

`semantics.dummy(f, a, evidence)` proves irrelevance only, and returns None when it cannot decide. Thresholds are anti-monotone per factor. Nothing else is assumed monotone, because S ↦ state(a) is measurably non-monotone.

### B2. Contrast and hybrid semantics

- Pipeline order: patches → candidates in array order → `sel` → `occ` records → per-record predicates (`trait`, thresholds, gate from `map`) → projection to the KeySpace → presence and attributes.
- A contrast is (x0, x1 as executed Configs, group evidence, comparison KeySpace). D is the executed diff, with |D| ≤ 6.
- h_S = run(x0 with the factors in S set to their x1 levels).
- The default comparison space is WHO ICD-10 (`hier:<sha>`). CM outputs are projected by exact+fallback and labelled a structural projection. Unmapped units stay as `unmapped` records, not absences. UNAVAILABLE medications are excluded from change targets.
- Each run stores declared and executed configs, and hybrids act on executed levels. Views show declared levels (L1) or executed levels (with a code link).
- Prep and ACM factors are `avail(S)` = false without a stored response, so no counterfactual is enumerated.
- Secondary targets (score level, class, granularity) use the same machinery with a categorical `state`.

### B3. Minimal-family algorithm

Oracle. Compute `suff[S] = (state_S(a) == state_D(a)) ∧ admissible(S)` for all 2^|D| subsets. Then:

```
sub[S]     = suff[S] ∨ ⋁_{i∈S} sub[S∖i]
minimal[S] = suff[S] ∧ ¬⋁_{i∈S} sub[S∖i]
```

This costs O(n·2^n). It handles inadmissible intermediate sets correctly. `a` changed iff state_∅ ≠ state_D, which forces ∅ insufficient and D sufficient. The nonmonotone flag is: some sufficient S has a non-sufficient admissible superset.

Method-side sound BFS:
1. Go by increasing |S|.
2. Skip S only if S ⊇ a found sufficient set, or S contains a factor with a valid dummy certificate.
3. Evaluate the rest.

Every S it evaluates has all proper subsets evaluated or skipped, so any sufficient S it finds is truly minimal. If the budget runs out mid-level, the result is a verified partial family, flagged incomplete.

### B4. Identification reference (per case, query `a`, view `v`, capability `r`)

**History and observation.**
- A history is h = (E, κ). E is the evidence for `a`'s candidates (exact when visible, abstract when hidden). κ = (κ0, κ1) are code variants.
- Each history determines a truth table τ_h through `core.run`, hence a family F(h).
- The observation o_{v,r}(h) contains:
  - declared configs and the stored finals Out_∅ and Out_D (always);
  - E if responses are visible; top-1 only under that ablation; nothing under L1;
  - κ if the code link is visible; otherwise replay uses the declared code and must reproduce the finals;
  - per-candidate decisions with reasons at executed x0 and x1 under L2-M (winners only under ablation);
  - replay results {S ↦ Out_S} for S ∈ avail (R-A and R-B for post-ACM D; none under R-C).
- W(c, a, v, r) = { F(h′) : h′ ∈ U, o(h′) = o(h*) }.

**Universe U (finite, declared).**
- Candidate symbols: (es-band, cs-band, top1, trait-class, type, map-class). Bands are cut only at the x0/x1 levels of D's factors. The trait-class is (NEG, LOW, FAM, HYP ∈ {≤.60, (.60,.65], >.65, none}, DXS). Symbols are merged by behaviour signature (identical pass-vector over 2^D).
- A bundle is an ordered sequence of at most L = 4 symbols; order matters through `occ`. Expand breadth-first, deduplicating on the class (τ, o). Mark `saturated` iff length L adds no new class. Each class is realized as a synthetic one-medication response run through `core.run`.
- Variants K: at most 2 options per factor from F1's hypothesis space (HYPOTHETICAL veto >0.65 in code vs ≤0.60 in docs; `occ` last vs first; gate on/off; one vs two threshold constants). At most 3 factors drifted, so |K| ≤ 64 pairs.

**Bounds and validation.**
- W_hi is marginal in `a`; other associations are unconstrained.
- W_lo keeps only classes whose witness lifts to the true group. Lifting edits only `a`'s candidates, keeps the sort invariants, reruns, and requires every visible observable unchanged.
- If |W_lo| = 1 < |W_hi| the case is `ident_indeterminate`: reported, excluded from primary denominators.
- Universe adequacy test: every one of the 804 corpus truth tables must be generated by U. The families realized in the corpus with the same observation must lie inside W_lo.
- Scope: identification is relative to U. A missing witness is not global identification.

**Applicability.**
- L1 × {R-A, R-B} is n/a.
- R-A ≡ R-B unless D contains prep or ACM factors.
- N1/N2 restrict `avail` to the policy's executable factor set: thresholds, trait sets, gate and HYPOTHETICAL rule for 405a10c; the three parameters of HEAD's SQL for V2.

### B5. Output taxonomy, scoring, statistics

**States.**
- Categorical:
  - `explicacao_verificada` (one family)
  - `alternativas` (two or more families)
  - `ausencia_de_mudanca`
  - `compativel_com_variabilidade`
- Abstentions: `informacao_insuficiente`, `orcamento_esgotado`, `contrafactual_indisponivel`.
- `falha_de_execucao` is separate. Its rate is reported and it never counts as absence.

**Scoring per query** (truth = changed(a), F*, W_lo, W_hi):

| output | outcome |
|---|---|
| verified | Wrong if ≠ F*. Otherwise `correct_sustained` if \|W_hi\| = 1, `unduly_exclusive` if \|W_lo\| > 1 (even if right by chance), else indeterminate. |
| alternatives 𝒜 | `correct_sustained` iff 𝒜 = W (with \|W\| > 1). Wrong if F* ∉ 𝒜. `unduly_exclusive` if F* ∈ 𝒜 ⊊ W_lo. Loose (𝒜 ⊋ W_hi, or \|W\| = 1) counts as non-committal: coverage loss only. |
| no change | Correct iff not changed(a). |
| within variability | Correct iff the truth is variability-only (simulator or campaign; n/a in the deterministic core). |
| abstention | Never an error. Appropriate iff \|W_lo\| > 1, or the needed evaluations exceed the budget, or `avail` is false. Otherwise "unnecessary". Counterfactual-unavailable cases leave the coverage denominator. |

- **Backing.** A "verified" claim needs backing, checked by the evaluator:
  - `eval`: an env-log evaluation;
  - `trace`: a stored-trace derivation;
  - `logic`: |D_exec| = 1 with the executed config visible.
  Unbacked claims count as `unduly_exclusive`. A false dummy certificate makes the answer wrong.
- **Metrics.**
  - Coverage = correct_sustained / eligible.
  - Raw coverage = categorical / eligible.
  - Selective risk = (wrong + unduly) / categorical.
  - Null control: false attributions per contrast, and the fraction of groups with at least one (primary).
  - Cost: raw and amortized.
- **Statistics.**
  - Paired cluster bootstrap by group (B = 2000, fixed seed).
  - Non-inferiority test of L2-R minus L2-M against −0.02, one-sided.
  - Holm correction over the 3 primary contrasts.
  - Zero-event group-level exact bound 1 − α^{1/n}.
  - Coverage at 5% risk by sweeping frozen knobs (verification strictness, variability θ) on cal.
  - Precision simulation for sizing the test.

## C. Scenario families

**Common rules.**
- Evidence is real responses plus optional flagged `patch` factors. Patches are order-preserving edits, validated for these invariants: 0 or 5 concepts sorted descending, no top ties, unique `Id`, scores in [0, 1].
- `origin ∈ {real, semisynthetic}` lives only in the truth package.
- Per contrast, at most 25 changed and 25 unchanged queries, with recorded inclusion probabilities and the same ratio in every family.
- Dev, cal and test use different parameter values (for example test-only thresholds 0.575 and 0.625). Test parameters are sealed.

| family | generation | contrasts per group |
|---|---|---|
| N | (a) transport-metadata-only change, D = ∅, level-2 equal. (b) Only dummy factors (`map`, a threshold moved into an empty band, chosen by `semantics.dummy`). (c) Real repetition: two medications with identical submitted text, all expected NO_CHANGE. (d) Stochastic: simulator only. | 3 |
| F | One factor: `ent_thr` ∈ {0.55, 0.65}, `icd_thr` ∈ {0.55, 0.65}, `trait` variants. Boundary patches set a borderline score to exactly t and to t − 1e-9. F* = singletons. | ~7 |
| M | `map` pairs with WHO fixed. Unmapped units kept. Granularity change flagged via the ancestor relation. | ~5 |
| O | `occ` × `sel`, plus `first_upsert`. Prefer high-multiplicity groups (83% of pairs have >1 occurrence, max 48). Optional flagged patch swapping two entities' array positions. | ~5 |
| X | (i) The real `V1_TO_V2` bundle. (ii) Oracle-guided rejection sampling: k ∈ {3..6}, at least one verified no-effect factor, at least one opposing pair, quotas over shapes (single, multi-set, interaction, non-monotone). (iii) The §7.2 example as `test_only`. | ~6 |
| I | The same executions crossed with L1, L2-R, L2-M, single ablations A1–A6 and 4 predefined combinations, times R-A/R-B/R-C (n/a cells marked). New executions only for declared ≠ executed drift (HYPOTHETICAL rule, gate, `occ`) on a subset of F/X. | – |
| P | Catalogued only. Returns `contrafactual_indisponivel` until the campaign or simulator exists. | – |

**Leakage controls.**
- HMAC-SHA256 ids with a key kept only in truth.
- Uniform file names, constant mtimes, shuffled query order.
- No family, seed, edit or shape in any name or content.
- The declared config exposes only the public schema.
- Truth lives in a separate directory that is never mounted for methods.
- Canary tests.

## D. Methods (all against `Env`)

**M (proposed).**

```
explain(env, Q):                                           # shared budget per contrast
  r0, r1 = env.contrast(); d0, d1 = env.config(r0), env.config(r1)
  inv = inventory(env)                                     # artifact kinds x ClaimState
  if env.can_evaluate():
      ok = evaluate(∅) == final(r0)  and  evaluate(all) == final(r1)     # 2 cached evals
      K  = library variants reproducing both finals   if not ok else {declared}
      if not K: return {a: INSUFICIENTE("replay_invalido")}
  D0 = declared_diff ∪ executed_diff ∪ variant_implied ∪ first_divergent_stage(inv)
  for a in Q:
      if state(final r0, a) == state(final r1, a): out[a] = NO_CHANGE (or WITHIN_VARIABILITY via L3 refs); continue
      D[a] = {f in D0 : no dummy certificate (trace under L2-M, parsed responses under L2-R)}
  F, complete = bfs(env, changed, D)                       # shared evals, sound under non-monotonicity
  for a: BUDGET(partial F) if not complete
         else families = {F(κ) : κ in K}                   # 1 -> VERIFICADA, >=2 -> ALTERNATIVAS
         INSUFICIENTE(reason) if evidence for a is hidden and |D[a]| > 1 and no replay
```

**B0.** Unchanged → NO_CHANGE; changed → `informacao_insuficiente("output_diff_only")`.

**B1.** Take D_decl, the declared diff. One factor → verified {{f}}. More than one → alternatives {{{f}} for each f}. None → insufficient.

**B2.** Compare materialized artifacts stage by stage; L1 and L2-R degenerate to B1. Output alternatives over singleton factors of the first divergent stage, tagged `noncausal`.

**B3 (native reference).** Replay-validate, then set D to the declared diff plus the first-divergence factors. Evaluate all singletons and all leave-one-out complements, at most 2|D| + 2 evaluations. Report the sufficient singletons; if none, D itself when every leave-one-out is insufficient. It does no dummy pruning and no identification reasoning.

**BugDoc adaptation (vendored `StackedShortcutStandalone`, pinned to `75e3d26`).**
- Parameters are the factors of D with values {x0 level, x1 level}.
- `function(params)` = `env.evaluate({f : params[f] == x1})` and returns True when `state(a) == state_x0` (BugDoc uses True = success).
- Call with `historical_runs=[[], []]`, because `load_runs` creates a file named after the entry point. Set `max_iter = budget`. Catch `BudgetExhausted`.
- Convert each `believeddecisive` conjunction to S = its x1-valued factors, then take the minimal antichain.
- **Semantic caveat.** BugDoc's "definitive" cause holds against every good instance seen, whatever the other parameters are. Ours is sufficiency in the x0 context. In cancellation cases the conjunction carries x0-valued literals, which we drop; document this.
- Its initial exploration is a pairwise combinatorial design. Later shortcut steps ignore `max_iter`, so the Env meter must cut it off.
- Porting Shortcut and DDT in-process is a documented deviation, done only if needed.

## E. Test strategy

- **V1 fidelity** (`dumps` marker): entity, trait and md at 0 diffs; the funnel 274,010 → 265,587 → 259,198 → 171,713 → 43,194 → 43,194; extend at 44,233 rows with id = 23,301 + rank, labelled "inferred rule".
- **V2 fidelity:** `entity_icd`, `entity_trait` and `cutoff_audit` exact; `md` presence exact. Then md attributes (GROUP_CONCAT float text, MAX of ids), with a `tie_flag` policy.
- **SQL cross-validation** (`docker`):
  - Sample about 100 hybrids in the V1-expressible sublattice on 200 medications. Compare against 405a10c with patched constants.
  - Do the same for HEAD's SQL with its 3 parameters.
  - Publish a coverage table of which cells have a historical oracle.
  - Never import the historical `db_utils.py`. Use our own shim and a throwaway container password.
- **Oracle unit tests.**
  - The §7.2 example: minimal sets {threshold} and {candidate}, and a third no-effect factor in none.
  - A cancellation example and an interaction example.
  - Hypothesis property tests against a naive O(3^n) implementation: antichain, each member sufficient, no proper subset sufficient, every sufficient set covered.
  - BFS equals the oracle at unlimited budget, and is a verified subset with the incomplete flag otherwise.
  - Dummy-test soundness against brute force.
- **Identification tests.**
  - The §7.4 witness pair under L1 gives |W| = 2.
  - L2-M gives |W| = 1.
  - The HYPOTHETICAL doc/code drift gives 2 families under L1 and 1 with the code link.
  - Universe adequacy and saturation checks.
  - A lifting-failure case where a shared entity's rank couples two associations.
- **Isolation tests.**
  - The audit hook denies a canary truth file, sockets, subprocess, `listdir` outside the view, and imports of `thesisbench.pipeline`, `oracle` and `scenarios`.
  - The broker RPC is the only way to `evaluate`.
  - Leak scan over names, keys and decompressed contents.
  - Views satisfy L1 ⊂ L2-R ⊂ L2-M byte-for-byte per artifact, and each ablation removes exactly one item.
  - Id-order unlinkability.
- **Metrics tests:** synthetic outputs for every state × truth cell. Also seeded bootstrap reproducibility, non-inferiority boundary, Holm, and Clopper–Pearson checked against scipy in dev.
- **Other:**
  - Campaign dry-run default, hard cap, and the 2,250 / 1,800 formula.
  - PROV: attempt id ≠ sha256, secret scrub.
  - A 5-group end-to-end run.

## F. Work breakdown

D = deep reasoning, M = medium, S = straightforward. One owner per file set.

| # | Task (owned files) | Deps | Acceptance | Type |
|---|---|---|---|---|
| T0 | Bootstrap: `pyproject.toml`, `.python-version`, `.gitignore`, `tests/conftest.py`, CI | – | `uv sync && uv run pytest` green on 3.12 and 3.14 | S |
| T1 | Spec: `docs/SPEC.md`, `tests/data/spec_examples.json` | – | User-reviewed; every definition has a worked example (F, W, state, score) | D |
| T2 | `data/dumps.py`, `data/store.py` | T0 | Counts match the matrix; float-exact; api_response in ≤15 s | S |
| T3 | `pipeline/{catalog,evidence,core,trace,mapping,semantics,equality}.py` | T1, T2 | §0 fidelity numbers; 64 hybrids of the full corpus ≤120 s; dummy tests sound | D |
| T4 | `pipeline/tables_v1.py`, `tables_v2.py` | T3 | Full-row equality, extend ids, V2 md attributes | M |
| T5 | `oracle/{hybrids,families,truth}.py` | T1, T3 | §7.2 example; properties vs naive | D |
| T6 | `oracle/{universe,identify}.py` | T5 | Spike in week 1; adequacy over 804 tables; W_lo ⊆ W_hi | D |
| T7 | `prov/*` | T0 | ClaimState ledger; JSONL round-trip | S |
| T8 | `data/{groups,splits,sampling}.py`, `repro/{corpus_groups,split_manifest}.csv` | T2 | Deterministic; dev ⊇ inspected ids; giant-component report; `SealedError` for test | M |
| T9 | `scenarios/*` | T3, T5, T8 | Shape quotas; validators; edits flagged in truth only | M/D |
| T10 | `views/*` | T1, T4, T9 | Projection, leak and hook tests | M |
| T11 | `env/*` | T3, T10 layout | Budget, cache, capabilities, raw and amortized meter | M |
| T12 | `methods/{base,b0,b1,b2,search}.py` | T11 | BFS equals oracle; mapping rules tested | M (search D) |
| T13 | `methods/m.py` | T6, T12 | Unlimited-budget L2-M/R-A equals the oracle in 100% of cases; valid certificates | D |
| T14 | `methods/b3.py` | T12 | Same budget as M; replay-mismatch abstention | M |
| T15 | `methods/bugdoc_adapter.py`, `third_party/bugdoc` | T11 | Upstream tests pass; toy root causes recovered | M/D |
| T16 | `eval/{score,metrics}.py` | T1, T5, T6 | Every state × truth cell tested | D |
| T17 | `eval/{stats,precision_sim}.py` | schema from T16 | Matches scipy; bootstrap coverage on simulated clusters | D |
| T18 | `historical/*` | T3, T4 | Study A pilots; cross-validation coverage table | M |
| T19 | `campaign/*` | T7, T8 | Dry-run default; hard cap; estimator formulas | M |
| T20 | `annotation/*` | T8 | Inclusion probabilities; kappa tests | S |
| T21 | `runner/*` | T9–T16 | Efficient-matrix e2e on 5 groups | M |
| T22 | `tests/audit/*` (independent naive oracle, isolation red-team) | gates P2 and P4 | Zero divergences | D |

**Critical path:** T1 → T3 → T5 → T6 → T9/T10 → T11 → T13 → T16 → T21 → T22 (P4 freeze).
- Wave 1: T0, T1, T2, T7, T17 skeleton.
- Wave 2: T3, T8, T19.
- Wave 3: T4, T5, T18, T20.
- Wave 4: T6 spike, T9, T10.
- Wave 5: T11, T12, T14, T15, T16.
- Wave 6: T13, T21.

## G. Risks and early de-risking

1. **Definitions drift (W vs F, "verified").** T1 comes first, with worked examples, user sign-off before T5/T6/T16, and the independent naive oracle in T22.
2. **V2 reproduction.** Measured OK: 0 diffs, no ties. The residual risk is md attributes (GROUP_CONCAT float text, MAX of ids). T4 tests those first. Ties get a `tie_flag`, are excluded from attribute targets, and never from presence targets.
3. **Identification blow-up.** Measured 804 truth tables, and the universe is classes, not histories. Saturation flags and W_lo/W_hi bound it. Unsaturated cases are excluded and reported. T6 spikes first on |D| = 6 under L1.
4. **BugDoc.** It exists but has the constraints in section D. If fidelity tests fail, restrict superiority claims per §10.1.
5. **Hybrid cross-validation coverage.** 405a10c can be patched only for thresholds, trait rules, gate and HYPOTHETICAL. Cells mixing `occ`, `sel` or V1-V2 semantics have no historical SQL oracle. Publish the coverage table and cover those cells with T22's independent reimplementation.
6. **H2/L3.** No historical variability exists. Keep the simulator separate and label it as such. Expect an inconclusive H2 per §9.5, and report the detection limit.
7. **Sealing and leakage.** Never generate test truth before the freeze tag. Lint against test ids appearing in code. Use `SealedError`.
8. **Group construction.** The near-duplicate threshold is fixed a priori (0.90 shingle Jaccard). Guard against a giant component, tuning on structure only, and log it.
9. **Toolchain.** The default Python is 3.14. PyPI is unverified. Docker replay takes about 13 min, so use a sampled DB.
10. **Credentials.** Never copy `db_utils.py`, and add a CI secret scan.

### Critical Files for Implementation
- /home/vinicius/code/ThesisBench/docs/SPEC.md (to create)
- /home/vinicius/code/ThesisBench/src/thesisbench/pipeline/core.py (to create; port semantics from /home/vinicius/healdb-reconstrucao/code/405a10c/src/nlp_extraction/link_medications_with_diseases.py and /home/vinicius/code/HealDB/src/nlp_extraction/link_medications_with_diseases.py)
- /home/vinicius/code/ThesisBench/src/thesisbench/oracle/families.py (to create)
- /home/vinicius/code/ThesisBench/src/thesisbench/oracle/identify.py (to create)
- /home/vinicius/code/ThesisBench/src/thesisbench/views/isolation.py (to create)
