# Ambiente, BugDoc, Why-Diff, API e preço do InferICD10CM

> Relatório de subagente (Sonnet) produzido em 2026-09-30 na sessão de planejamento, somente leitura.
> Números aqui são de rascunho: re-derivar em código versionado antes de citar em relatório.
> Onde se lê ThesisBench/thesisbench, leia healdb-attribution-bench/habench.

# Read-only environment and literature check for ThesisBench

I installed and wrote nothing, and made no AWS API calls. Everything was read-only GETs plus PDF-to-stdout extraction.

## 0. Read first: the ThesisBench remote is not empty
- **Local checkout:** `/home/vinicius/code/ThesisBench` is `main` at `f4768b8 first commit`, README only, clean. It reports "up to date" only because remote refs were never fetched. I did not fetch.
- **Remote:** `VINIClUS/ThesisBench` is PRIVATE, and my token has admin/push. Besides `main` it has branches `ccr-014ac6b1-g99nly` and `-formal`, plus open **PR #1**, "Initial implementation of ThesisBench v0.1.0". That PR has 56 commits, 369 files and about +85k lines. It was last updated 2026-09-30T13:39Z, minutes before my check, so a cloud session may still be pushing.
- **What it is:** a different product from the planned benchmark. It is a Portuguese-language local CLI for rubric-based, evidence-locatable thesis analysis. It uses `src/thesisbench`, SQLite+FTS5, and `formal/` Alloy/TLA+/Lean. Its tests forbid network and paid APIs. There is no `.claude/` on that branch.
- **Host mismatch in its `CLAUDE.md`:** it pins CPython 3.13.15 (uv here has 3.13.14). It calls system Python "3.11 / SQLite 3.45.1" (here 3.14.4 / 3.46.1). The uv Pythons here bundle SQLite 3.53.1 with FTS5, which meets its 3.51.3 floor.
- **Decision needed:** which ThesisBench is meant (same repo, or a new repo or subdirectory). Don't push to `main` or those branches unprompted.

## 1. Environment
- **Python:** `/usr/bin/python3` is 3.14.4 (PEP 668, so use a venv or uv). uv-managed 3.12.13, 3.13.14 and 3.14.6 are in `~/.local/bin`.
- **Tools:** uv 0.12.4, pytest 9.0.2, git 2.55.0, gh 2.96.0, aws-cli 2.35.20. No poetry. No mysql/mariadb client (the `mysql:8.0.33` image ships one).
- **Docker:** 29.8.0 with Compose v5.5.1, daemon reachable.
  - Running postgres, neo4j and garage containers belong to another project (`agent-context-test-*`); leave them alone.
  - Local images include mysql:8.0.33, python:3.12-slim, python:3.13-slim, python:3-alpine and alpine:3.
  - Port 3306 is free.
- **Resources:** 8 CPUs, 15 GiB RAM (9.2 free), 224 GB free on `/home`.
- **Importable:** system python3 has only numpy 2.3.5, PyYAML 6.0.3 and pytest 9.0.2. The uv Pythons are bare. Missing everywhere: pandas, scipy, pyarrow, duckdb, pydantic, boto3, mysql.connector, sqlalchemy, prov, networkx, statsmodels, hypothesis. PyPI is reachable, and `prov` is 3.2.2 (Python ≥3.10).
- **AWS:** `/home/vinicius/.aws/config` has `[default]` with region `us-east-2`. `/home/vinicius/.aws/credentials` has `[default]` with a key id and secret and no session token, so they are static keys.
- **Env vars:** OPENAI_API_KEY, ANTHROPIC_API_KEY, AWS_ACCESS_KEY_ID, AWS_PROFILE and GOOGLE_APPLICATION_CREDENTIALS are all unset.
- **gh:** it authenticates only through the `GITHUB_TOKEN` env var; its keyring login is invalid. `git ls-remote` on the private remote works.
- **Custom agents:** none exist. `~/.claude/agents`, `HealDB/.claude/agents` and `ThesisBench/.claude` are absent. `HealDB/.claude` holds only `settings.local.json` and a headroom marker. Marketplace-cache plugin agents exist (enablement unchecked) and use `model: sonnet|opus|inherit`.

## 2. BugDoc (arXiv:2004.06530, checked against the PDF text)
- **Availability:** `github.com/VIDA-NYU/BugDoc` is MIT (source headers carry an NYU BSD-style notice) and Python, last pushed 2026-07-13.
  - PyPI `bugdoc` is only v0.1 (2020), pinning Django==1.11.28 and nose==1.3.7, so it is not installable on modern Python.
  - The repo is 0.2.0. Root `pyproject.toml` omits `six`, which `debugging_decision_trees.py` imports (verify).
  - Vendoring or re-implementing is easier than installing.
- **API:**
  - The parameter space is `dict[name -> list of values]`.
  - The predicate is `function(params: dict) -> bool`. True means succeed, False means fail, None means it could not run.
  - History is `historical_runs=[rows, rows]`, with rows `[v1..vn, result]` in dict order. Otherwise it is a JSON-lines file named by `entry_point`, created if missing.
  - `StackedShortcutStandalone(k=4, max_iter, function=f).run(...)` returns a list of conjunctions `[(param_index, value)...]`, read as a disjunction.
  - `DebuggingDecisionTrees` returns `(causes, tree, n_runs)`.
  - Only these two classes accept `function=`. `Shortcut` and `StackedShortcut` need a ZMQ worker.
- **Definitions (Defs 1–5):**
  - The evaluation E is deterministic and returns succeed or fail.
  - A hypothetical root cause is a conjunction of (parameter, comparator, value) triples. It is satisfied by at least one failing instance and by no observed succeeding one.
  - Definitive means that no instance anywhere in the universe U satisfying it succeeds.
  - Minimal definitive means no proper subset is definitive.
  - It is a sufficient condition, not a counterfactual. Cost is the number of new executions beyond history.
- **Shortcut:**
  1. Take a failing CPf and a succeeding CPg that is disjoint (differs on every parameter).
  2. Set CPcur = CPf.
  3. For each parameter p in fixed order, run CPcur with p := CPg[p]. If it still fails, adopt it.
  4. D = CPcur ∩ CPf. If any observed succeeding instance contains D, return empty.
  - It needs at most |P| new runs. It is never over-long, but can be truncated. It is exact when all causes are singletons or pairwise "sufficiently different" (Thms 1–3).
- **Stacked Shortcut:** take k mutually disjoint succeeding instances, all disjoint from CPf. Run Shortcut against each and combine the results. It is correct if there are at most k distinct minimal causes (Thm 5), and costs at most k·|P| runs.
- **Debugging Decision Trees:**
  1. Fit a full, unpruned tree on history. Nodes are (parameter, {=,≥,≤,≠}, value).
  2. Each pure-fail path is a suspect.
  3. Sample new instances from the Cartesian product restricted by the path.
  4. If all fail, assert the cause. If any succeeds, rebuild the tree and try another suspect.
  5. Simplify the result with Quine–McCluskey.
  - The worst case is exponential.
- **Code differs from the paper in these ways:**
  - Standalone Stacked Shortcut never resets `cf` to CPf between good instances.
  - Shortcut without a disjoint pair picks a random pair; the paper says to maximise differences.
  - DDT `entropy` uses `log(x)//log(2)`, which is floor division.
  - DDT calls a path definitive when only the sampled tests fail, not exhaustively.
  - Quine–McCluskey runs only in the CLI, not in the library class.
  - With no history, each class first runs a pairwise covering array, a bootstrap cost the paper does not count.
  - Standalone mode appends each execution twice, doubling `max_iter` accounting. This is as read from the code.
- **Benchmark use:**
  - Count executions with a wrapper around the callable.
  - Compute ground truth by enumerating the declared domains.
  - Use paper Example 1 (Tables 1→2) as a golden test. The expected D is {LibraryVersion=2.0}.
  - The last new row of Table 2 duplicates CPg, so it costs 2 executions with memoisation and 3 without. You need a counting rule.
  - Theorems 1–5 give ready-made property tests.

## 3. Why-Diff (IEEE Access 7:34973–34990)
- **Code:** I found no public code. I searched GitHub, the e-science-central org and Missier's repos. `prsuyal/why-diff` is unrelated. The reference implementation used eScience Central plus Neo4j, so ask the authors. Full text is at `eprints.ncl.ac.uk/256703`, and the predecessor PDIFF is arXiv:1406.0905.
- **Framing:** it is passive. It re-executes nothing and needs only two traces, unlike BugDoc, which needs an executable pipeline and a predicate.
- **Inputs:**
  - Two W3C PROV graphs of runs of W and an edited W'. They use only Entities and Activities, with `used` and `wasGeneratedBy` edges. Nodes carry properties such as block config, library versions and data hash.
  - User-defined `equal()` and `match()`. In the paper, activities match by block-instance id, and entities by name or id.
- **Algorithm:**
  1. TraverseAndMatch walks both graphs in lockstep from the input entities. It compares entities, then the activities that used them, then the entities those generated, until one graph runs out. Leftovers go to UM1/UM2, and outputs are force-paired.
  2. Resync tries UM1×UM2 pairs to catch out-of-order nodes.
  3. It builds a delta graph. Matched pairs merge as x≈y, matched-but-unequal pairs are highlighted, and unmatched nodes become Nodes_Deleted (from PG1) or Nodes_Inserted (from PG2).
  - It makes O(n·m) comparisons and models activity insert, delete and update.
- **Adapting it:** you need stable activity and entity IDs for `match()`. Natural-language explanations are left as future work in the paper.
- **Local PDFs:** `/home/vinicius/.claude/projects/-home-vinicius-code-HealDB/9248441b-d15c-4972-94af-d5d37c40682a/tool-results/webfetch-1790775482633-lom349.pdf` (BugDoc) and `.../webfetch-1790775619355-l605pr.pdf` (Why-Diff). `pdftotext` is installed.

## 4. Comprehend Medical InferICD10CM and LLM pricing
- **Request:** only `{"Text": string}`. It is required, 1–10,000 characters, UTF-8, English only. There is no model-version selector.
- **Response:** `Entities[]`, `ModelVersion` and `PaginationToken`.
  - Each entity has Id, Text, Category, Type, Score, offsets, Traits, Attributes and `ICD10CMConcepts[{Code, Description, Score}]`.
  - `ModelVersion` is a string in `n.n.n` format. It is the only version signal and cannot be pinned.
  - The dev guide says codes come from the "2019 version" of ICD-10-CM.
- **Limits:** 40 TPS and 40,000 characters per second. The quotas page says "10 KB" for sync documents, while the API reference says 10,000 characters. A batch document can be up to 20,000 characters.
- **Price source:** the pricing page's table did not render. The figures come from AWS's public Price List file for us-east-2 (version 2026-09-11), fetched by plain HTTP GET. The parse reproduced AWS's worked examples for NERe ($0.01/unit) and SNOMED ($0.0075/unit).
- **Price:** a unit is 100 characters, with a minimum of 1 unit per request. Sync and batch both cost $0.0005/unit for the first 2M units a month, then $0.00025. That is $0.0005 for a short string, $0.005 per 1,000 characters and $0.05 for a full 10k request. The free tier is 85,000 units in the first month.
- **LLM prices per 1M tokens:**
  - gpt-4o-mini is $0.15 in, $0.075 cached and $0.60 out. I verified this on OpenAI's model page.
  - gpt-4.1-mini is $0.40 in, $0.10 cached and $1.60 out. This is from search-result summaries citing OpenAI and OpenRouter; the official page did not load.

## 5. Claude Code docs (checked against raw `sub-agents.md`)
- **`model:` field:** "`sonnet`, `opus`, `haiku`, `fable`, a full model ID such as `claude-opus-5-5`, or `inherit`". A full ID "Accepts the same values as the `--model` flag". The docs' examples are `claude-opus-5-5` and `claude-sonnet-5`; `claude-sonnet-5-5` is not listed.
- **Resolution order:** per-invocation `model` parameter, then frontmatter, then `CLAUDE_CODE_SUBAGENT_MODEL`, then the main model. With `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` (v2.1.257+), Claude Code ignores every definition's `model` field.
- **Nesting:** "By default, a subagent can spawn subagents of its own, up to three layers below the main conversation." Set `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` to change the limit, and "Set `1` to turn nesting off". To block one agent, "omit `Agent` from its `tools` list or add it to `disallowedTools`". The `Agent(agent_type)` allowlist "applies only to an agent running as the main thread with `claude --agent`".
- **Headless:** `claude -p "..." --model <alias|full name>` (example `claude --model claude-sonnet-5`).
  - **Permissions:** `--permission-mode` takes default, acceptEdits, plan, auto, dontAsk, bypassPermissions or manual. For `-p` the default mode is `default`, so unattended runs need a mode or `--allowedTools "Bash,Read,Edit"`. `--dangerously-skip-permissions` is "Equivalent to `--permission-mode bypassPermissions`".
  - **Other flags:** `--permission-prompts none`, `--output-format json` (includes cost), `--max-turns`, `--max-budget-usd` and `--agents` (JSON or file path).
  - **`--bare`:** it does not use the subscription login, so it needs `ANTHROPIC_API_KEY`, which is unset here. It also skips `.claude/agents`, so pass subagents with `--agents`.
  - **Version:** local Claude Code is 2.1.285, which meets every version gate cited (2.1.257, 2.1.259, 2.1.281).

Sources: [BugDoc repo](https://github.com/VIDA-NYU/BugDoc), [BugDoc docs](https://bugdoc.readthedocs.io/en/latest/), [Why-Diff ePrint](https://eprints.ncl.ac.uk/256703), [InferICD10CM API](https://docs.aws.amazon.com/comprehend-medical/latest/api/API_InferICD10CM.html), [CM pricing](https://aws.amazon.com/comprehend/medical/pricing/), [CM quotas](https://docs.aws.amazon.com/comprehend-medical/latest/dev/comprehendmedical-quotas.html), [gpt-4o-mini](https://developers.openai.com/api/docs/models/gpt-4o-mini), [gpt-4.1-mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini), [subagents](https://code.claude.com/docs/en/sub-agents), [CLI reference](https://code.claude.com/docs/en/cli-reference), [headless](https://code.claude.com/docs/en/headless).
