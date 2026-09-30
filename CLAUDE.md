# healdb-attribution-bench — rules for every session and subagent

This repo implements the experimental protocol `docs/protocolo/Protocolo_Experimental_HealDB_Revisado_v0_2.md`
(per-association change attribution under partial provenance, HealDB drug–disease pipeline).
Read `docs/SPEC.md` (when present), `docs/design/*.md` and your task brief in `docs/tasks/` before coding.

## Layout and ownership

- Package `src/habench/`; tests in `tests/`; human docs (Portuguese) in `docs/`; reproduction package in `repro/`.
- Each lead's brief lists the files it owns. Edit only files you own. `src/habench/types.py`,
  `pyproject.toml`, `CLAUDE.md` and `.claude/` belong to the main session: ask for changes via `BLOCKED:`.
- Adding a dependency: ask via `BLOCKED:` (main session edits `pyproject.toml`).

## Commands

- `uv sync` then `uv run pytest` (default run excludes `docker` and `paid` markers).
- Data-heavy tests: `flock /home/vinicius/hab-data/.heavy.lock uv run pytest -m dumps`.
- Environment (set in `.claude/settings.json`): `HAB_DUMPS_DIR` (extracted mysqldumps, read-only),
  `HAB_WORKSPACE` (`~/healdb-reconstrucao`, read-only), `HAB_DATA_DIR` (`/home/vinicius/hab-data`: snapshots,
  truth, views, runs, campaign — never inside the repo).

## Hard rules (security and money)

- Never read or copy `~/healdb-reconstrucao/src/prehist_git/`, `~/healdb-reconstrucao/out/prehist_nested.txt`,
  `~/healdb-reconstrucao/scripts/prehist_nested.sh`, anything under `~/.aws/`, or HealDB's `config.py`.
- HealDB git history: inspect only commits `0e43ed9`, `405a10c`, `c5b0db1`, `4895898`, `2d1dc7f`, `8ea0479`
  (HEAD). Never open archives (`.zip`, `.rar`, `.7z`) from HealDB history.
- Never copy passwords or connection strings from `db_utils.py` or the workspace replay scripts; a throwaway
  MySQL password comes from `HAB_MYSQL_PASSWORD`.
- No paid or external calls: never run the `aws` CLI, never call boto3 against real endpoints, never set
  `HAB_PAID_CALLS`, never use MCP tools. Campaign code defaults to dry-run; only the main session runs paid calls.
- No git remotes, no push.
- `tests/test_guards.py` scans the repo for secrets; mark a deliberate false positive with `secret-scan: ignore`.

## Scientific integrity

- The test partition is sealed: never materialize test truth, views or runs (raise `habench.types.SealedError`).
- Calibration, universe adequacy checks and shape quotas use dev/cal only.
- Every edit of an ACM JSON response is a semisynthetic intervention: flag it in the truth package only.
- At most 6 binary factors per contrast (declared bundles allowed).
- Method code sees only its view and the evaluation broker; it must not import `habench.pipeline`,
  `habench.oracle` or `habench.scenarios`, and view artifacts must not leak family names, labels or seeds.
- Algorithm comparisons use the same view; information comparisons use the same algorithm.
- Never treat a failed or missing execution as absence of an association.

## Shell caveats

- A hook rewrites shell commands through `rtk`. `git log` output is capped at 50 lines: use
  `rtk proxy git log ...` or `git rev-list`. Binary output of `git show <rev>:<file>` can be corrupted: use
  `git cat-file blob` in a script. rtk-filtered `grep` prefixes line numbers.

## Style

- Python 3.12, type hints, frozen dataclasses, small modules, no speculative abstractions.
- Identifiers and code comments in English; human docs in Portuguese.
- Deterministic seeds; tests with pytest, property tests with hypothesis.

## Workflow for leads

- Delegate implementation to `hab-worker` subagents with exclusive file ownership (max 3 at a time);
  write the deep parts yourself when the brief says so; review every diff; run the tests.
- Commit only your owned files, message `area: summary`, ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Keep `docs/status/<lead>.md` current: done, in progress, next, open questions, test status.
- On ambiguity about protocol semantics, stop and write `BLOCKED: <question>` at the top of your status file
  and in your final message; do not invent semantics.
