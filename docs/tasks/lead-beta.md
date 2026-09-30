# Lead β — protocol analysis, SPEC, then oracle, identification and evaluation

Read `docs/tasks/00_common.md` first. Status file: `docs/status/lead-beta.md`. Branch `lead-beta`.

## Owned files (exclusive)

`docs/analise/**`, `docs/SPEC.md`, `tests/data/spec_examples.json`, `tests/test_spec_examples.py`,
`src/habench/oracle/**`, `src/habench/eval/**`, `tests/test_oracle_*.py`, `tests/test_eval_*.py`,
`docs/status/lead-beta.md`.

## Inputs

The protocol; `docs/design/desenho_inicial.md` (§B1–B5, §C, §D, §E, §G are the starting point, not gospel);
`docs/design/mapa_codigo_healdb.md`; `docs/design/ambiente_e_comparadores.md` (BugDoc and Why-Diff semantics);
reports F1/F2 in `/home/vinicius/code/HealDB/doc/`; F3 `/home/vinicius/Downloads/Esboco_revisado_HealDB_IC_Unicamp(2).pdf`
(`pdftotext` is allowed).

## Chunk β1 — protocol analysis **[Opus]**

`docs/analise/00_analise_protocolo.md` (Portuguese), the "Analise" deliverable for the user:
1. Citation check: every `[F1 §x]`, `[F2 §x]`, `[F3 §x]`, `[E1–E4]` claim of the protocol against the source,
   as a table (claim, source section, status: confere / diverge / não verificável, note).
2. Internal consistency: numbers, budget arithmetic of §13, roles of §9.2, partition sizes, H1a/H1b/H2 wording.
3. Operational gaps and the resolution adopted in the SPEC (identification reference per view, scoring of
   alternatives, case where the declared diff does not reproduce x1, non-monotone sufficiency, budget unit,
   case vs group weighting, multiplicity, non-inferiority test, N1/N2 mapping, P family without new calls).
4. Preliminary empirical findings from `docs/design/` that change the design, labelled "a re-derivar"
   (e.g. ACM repeatable within a run → H2 only testable with the campaign or a declared simulator; `map` is a
   natural no-effect factor in WHO space; dev > 200; no score exactly at 0.60).
5. Threats to validity; 6. Proposed amendments for the confirmatory version.
Commit when done.

## Chunk β2 — SPEC **[Opus]** → GATE 2

`docs/SPEC.md` (Portuguese prose, English identifiers), precise enough for Sonnet workers to implement without
guessing. It must define, with at least one worked example each:
- association key and comparison spaces (§5.1); presence states (`UNAVAILABLE` ≠ absent); equality levels (§5.2;
  level 2 drops exactly the top-level `ResponseMetadata` object — the data layer already implements this);
- factor catalog: names, stages, levels, semantics, dummy (irrelevance) certificates, monotonicity facts; bundles
  (`V1_TO_V2`, `EXTEND`); `patch:<id>` semisynthetic edits and their invariants; ≤ 6 binary factors per contrast;
  test-only factor levels are drawn at the freeze from a sealed list and are **not** written in the SPEC;
- contrast and hybrid semantics; minimal-family definition and the oracle algorithm (§7.2–7.3), including
  non-monotone and inadmissible cases, and what happens when the declared diff does not reproduce x1;
- evidence profiles L1, L2-R, L2-M, L3-R, L3-M, N1, N2, ablations A1–A6 and combined losses, capabilities R-A/R-B/R-C,
  budget unit (one evaluation = one hybrid run of a whole document group) and the structurally n/a cells;
- identification reference: the declared finite universe U, `W_lo ⊆ W_hi`, saturation, `ident_indeterminate`,
  the witness construction, and when U is needed (L1, R-C, family I only; singleton under L2-R with R-A);
  adequacy is checked on dev/cal only;
- output taxonomy (categorical vs abstention, `falha_de_execucao` apart), the backing requirement for
  `explicacao_verificada`, the scoring table (correct-sustained, wrong, unduly exclusive, non-committal),
  metrics of §11 (coverage, raw coverage, selective risk, null-control group rate, per-class P/R/F1, set/family
  metrics, abstention by reason, costs raw and amortized), always stratified by origin (real vs semisynthetic);
- the environment API that methods see (`Env`) and the method output schema; isolation requirements;
- scenario families N, F, M, O, X, I (P catalogued only) and their generation rules;
- statistical analysis plan: estimands, paired cluster bootstrap by document group (B = 2000, fixed seed),
  non-inferiority L2-R vs L2-M at −2 pp, Holm over the 3 primary contrasts, zero-event bounds, coverage at 5%
  selective risk, precision simulation for sizing the test.
Also `tests/data/spec_examples.json` + `tests/test_spec_examples.py`: every worked example (at least the §7.2
example, a cancellation case, an interaction case, the §7.4 witness pair, a HYPOTHETICAL doc/code drift case,
one example per output state × truth cell) checked by a small brute-force reference written inside the test
(independent of any `habench` module).
**When the SPEC and its examples are committed, write `GATE2: ready for review` at the top of your status file
and stop.** The main session reviews, runs an independent audit and resumes you with the verdict.

## Chunk β3 — after GATE 1 and GATE 2 approval (you will be resumed)

- `oracle/{hybrids,families,truth}.py`: enumeration of 2^|D| hybrids through the core, minimal families
  (`sub`/`minimal` recurrences), non-monotone flag; property tests (hypothesis) against a naive O(3^n) reference.
- `oracle/{universe,identify}.py` **[Opus]**: spike first with |D| = 6 under L1; saturation; W_lo/W_hi.
- `eval/{score,metrics}.py` (every state × truth cell tested), `eval/{stats,precision_sim}.py` (bootstrap,
  NI, Holm, exact bounds; checked against scipy).
