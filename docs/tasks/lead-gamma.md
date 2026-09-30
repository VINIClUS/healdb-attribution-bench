# Lead γ — scenarios, views, isolation, environment, methods, runner

Read `docs/tasks/00_common.md` first. Status file: `docs/status/lead-gamma.md`. Branch `lead-gamma`.
Starts only after GATE 1 (core merged) and GATE 2 (SPEC approved). The SPEC is normative; the design notes are
background. Where they disagree, follow the SPEC; where the SPEC is silent, stop with `BLOCKED:`.

## Owned files (exclusive)

`src/habench/scenarios/**`, `src/habench/views/**`, `src/habench/env/**`, `src/habench/methods/**`,
`src/habench/runner/**`, `tests/test_scenarios_*.py`, `tests/test_views_*.py`, `tests/test_isolation_*.py`,
`tests/test_env_*.py`, `tests/test_methods_*.py`, `tests/test_runner_*.py`, `repro/scenario_catalog.yaml`,
`repro/evidence_views.yaml`, `docs/status/lead-gamma.md`.
Read-only for you: `third_party/bugdoc/` (vendored, unmodified), `src/habench/pipeline/**` and
`src/habench/data/**` (lead α), `src/habench/oracle/**` and `src/habench/eval/**` (lead β).

## Tasks (design §F numbering)

- **T9 scenarios** (`scenarios/`, `repro/scenario_catalog.yaml`)
  - Families N, F, M, O, X, I per the SPEC. P is catalogued only.
  - Semisynthetic `patch` edits must pass invariant validators. They are flagged only in the truth package.
  - At most 6 binary factors per contrast.
  - Shape quotas and any oracle-guided sampling use dev/cal only.
  - Test-only levels are read from a sealed file that does not exist yet. Until the freeze, any request for them raises `SealedError`.
- **T10 views** (`views/`, `repro/evidence_views.yaml`)
  - Profiles L1, L2-R, L2-M, L3-R, L3-M, N1, N2, ablations and combined losses.
  - Per-case view directories under `/home/vinicius/hab-data/views/<partition>/`.
  - HMAC ids with a key kept only under `/home/vinicius/hab-data/truth/`; uniform names; constant mtimes; shuffled order.
  - Byte-for-byte inclusion checks.
- **T11 environment** (`env/`)
  - The `Env` API from the SPEC.
  - A broker process runs hybrids through the core on behalf of the method. It enforces the budget (one unit per distinct evaluated set, cached), capabilities R-A/R-B/R-C and n/a cells.
  - Meter: evaluations, bytes read, CPU and RSS, raw and amortized.
- **Isolation** (`views/isolation.py`, `tests/test_isolation_*.py`)
  - An audit hook (`sys.addaudithook`) in the method process denies:
    - file access outside the view;
    - `/home/vinicius/hab-data/truth/`;
    - sockets and subprocesses;
    - imports of `habench.pipeline`, `habench.oracle` and `habench.scenarios`.
  - Tests: canary files, leak scan over names and decompressed contents, id unlinkability.
- **T12 methods** (`methods/base.py`, `b0.py`, `b1.py`, `b2.py`, `search.py`)
  - Method interface and output schema from the SPEC.
  - BFS minimal-set search that is sound under non-monotonicity and budget-aware.
  - Tests: BFS equals the oracle at unlimited budget, and returns a verified subset with an incomplete flag otherwise.
- **T14 B3** (`methods/b3.py`): native reference. Replay validation, then singletons and leave-one-out complements under the same budget as M.
- **T15 BugDoc** (`methods/bugdoc_adapter.py`)
  - Uses the vendored `StackedShortcutStandalone` (and `DebuggingDecisionTrees` only if needed). The Env meter cuts it off at the budget.
  - Documents the semantic difference: BugDoc's "definitive root cause" versus the SPEC's "sufficient in the x0 context".
  - Fidelity tests:
    - the upstream standalone tests pass;
    - the paper's Example 1 (Tables 1→2) recovers `{LibraryVersion=2.0}`;
    - property checks derived from Theorems 1–5 on synthetic pipelines.
- **T13 method M [Opus]** (`methods/m.py`)
  - You write it: inventory, replay validation, declared ≠ executed detection, dummy certificates, BFS, identification-aware output, L3 controls.
  - Test: M equals the oracle in 100% of cases under L2-M/R-A at unlimited budget.
- **T21 runner** (`runner/`)
  - Runs the efficient matrix (families × views × capabilities × budgets × methods) over dev or cal only, as a resumable batch.
  - Writes outputs under `/home/vinicius/hab-data/runs/`.
  - Includes an end-to-end smoke test on 5 dev groups.
- **Optional:** Why-Diff reimplemented from the paper (`methods/whydiff.py`), only if a fidelity test from the paper's own example is possible. Otherwise record the limitation in your status file.
