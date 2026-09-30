# Auditor — GATE 2 (SPEC review)

You are an independent Opus auditor. You did not write the SPEC. Read `CLAUDE.md` and
`docs/tasks/00_common.md` (environment facts apply; delegation is optional). You may run tests and scripts, but
you edit only `docs/auditorias/gate2_spec.md`. Do not modify the SPEC or any code.

## Inputs

- `docs/SPEC.md`, `tests/data/spec_examples.json`, `tests/test_spec_examples.py` (lead β, branch `lead-beta`).
- `docs/analise/00_analise_protocolo.md`.
- The protocol (`docs/protocolo/…v0_2.md`), `docs/design/desenho_inicial.md`, `docs/decisoes.md`, `docs/deviations.md`.

## Audit questions

1. **Conformance.** Does the SPEC contradict or drop any requirement of protocol §§5–8, 10, 11 or 14?
   Check each requirement.
2. **Implementability.** Could a Sonnet worker implement every definition without guessing? List every
   undefined term, missing edge case or ambiguous rule.
   - Examples to check: inadmissible hybrids; `UNAVAILABLE` medications; unmapped units; ties;
     `ident_indeterminate`; N/A cells.
3. **Correctness.**
   - Recompute every worked example by hand and run `uv run pytest tests/test_spec_examples.py`.
   - Check the minimal-family recurrences. Check that the method-side BFS is sound under non-monotonicity.
   - Check the identification construction. `W_lo ⊆ W_hi` must hold, and a truncated or unsaturated
     search must never count as identified.
4. **Scoring.**
   - Can a method game the metrics? Examples: always answering `alternativas` with all singletons;
     abstaining strategically; exploiting `ident_indeterminate` exclusions.
   - Every output state × truth cell must be defined. The backing requirement for `explicacao_verificada`
     must be checkable by the evaluator.
5. **Leakage and integrity.**
   - The SPEC must not contain test-only factor levels.
   - Views must not leak labels.
   - Calibration and adequacy must use dev/cal only.
   - Semisynthetic edits must be flagged in truth only.
   - Algorithm comparisons must use the same view; information comparisons must use the same algorithm.
6. **Statistics.**
   - Estimands and cluster bootstrap by document group.
   - Non-inferiority at −2 pp, one-sided.
   - Holm over the three primary contrasts.
   - Zero-event bounds.
   - Coverage at 5% selective risk calibrated on cal.
   - Precision simulation.
7. **Feasibility.** Is the universe size and runtime plausible for about 1,000 groups × families × views ×
   budgets on 8 CPUs and 15 GiB? Name the bottlenecks.

## Output

`docs/auditorias/gate2_spec.md` (Portuguese):
- Every finding carries a severity (**bloqueante / importante / menor**), a location (SPEC section or
  example id), the problem, and a concrete fix.
- A closing verdict: **aprovar**, **aprovar com correções** (list the mandatory ones) or **reprovar**.

Commit it on your branch. Your final message (≤ 300 words) gives the verdict, the count of findings per
severity, and the blocking findings in one line each.
