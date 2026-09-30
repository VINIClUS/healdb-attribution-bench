# Common instructions for lead sessions

You are an Opus lead running headless (`claude -p`) in a git worktree of `healdb-attribution-bench`, on your own
branch. The main session (also Opus) orchestrates, reviews, runs Docker and paid steps, and merges your branch at
gates. Nobody can answer you interactively: when blocked, write it down and stop (see "Blocked").

## Read first

1. `CLAUDE.md` (hard rules — they override anything else).
2. `docs/protocolo/Protocolo_Experimental_HealDB_Revisado_v0_2.md` — the protocol you implement. Read it fully.
3. Your brief (`docs/tasks/lead-<name>.md`) and the design notes it cites in `docs/design/`.
   `docs/design/desenho_inicial.md` is the reference design; sections are cited as "design §X".
4. `docs/decisoes.md` and `docs/deviations.md`.
5. If you are resumed: your status file `docs/status/lead-<name>.md` first.

## Environment facts

- Shell commands containing `$VAR` expansion are blocked by the permission layer. Use literal paths:
  data `/home/vinicius/hab-data`, dumps `/home/vinicius/healdb-reconstrucao/x`, workspace
  `/home/vinicius/healdb-reconstrucao`. Python code reads `HAB_DATA_DIR`, `HAB_DUMPS_DIR`, `HAB_WORKSPACE`
  from `os.environ` with those literal defaults.
- Allowed shell commands: `uv`, `git`, `ls`, `cat`, `head`, `tail`, `wc`, `find`, `grep`, `sha256sum`,
  `md5sum`, `mkdir`, `cp`, `mv`, `diff`, `sort`, `python3`, `unzip -l`, `unzip -p`, `date`, `echo`, `pdftotext`,
  `touch`, `rm`. No Docker (the main session runs Docker steps). Run Python through `uv run`.
- Run `uv sync` once in your worktree before testing.
- Heavy data runs: `uv run pytest -m dumps <files>`, one at a time per lead (15 GiB RAM shared by several
  sessions). The default `uv run pytest` excludes `dumps`.
- Dependencies: to add one, write `REQUEST: dependency <name> — <why>` in your status file and continue with
  what you can; the main session edits `pyproject.toml`.

## Delegation (Opus manages Sonnet)

- Use the Agent tool with `subagent_type: "hab-worker"` (runs on Sonnet). Give each worker: goal, the exact
  files it owns (exclusive), spec/design sections, acceptance tests, commands to run.
- At most 3 workers at a time. Never give two workers the same file.
- Write yourself the parts your brief marks **[Opus]**. Review every worker diff (`git diff`) and rerun the
  tests yourself before committing.

## Checkpoints and status

- Commit after each finished unit with green tests, only your owned files, message `area: summary`, ending with
  the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Keep `docs/status/lead-<name>.md` current (Portuguese is fine), with sections:
  `Estado` (one line), `Feito`, `Em andamento`, `Próximo`, `Testes` (exact result lines), `Números re-derivados`
  (value, command, file), `Perguntas / BLOCKED`, `Desvios propostos`, `REQUEST`.
- Never edit files you do not own, `docs/deviations.md` or `docs/decisoes.md`: propose in your status file.

## Blocked

On a protocol-semantics ambiguity you cannot resolve from the protocol, the design notes or the spec: write
`BLOCKED: <question, options, your recommendation>` at the top of your status file, commit, finish the other
independent work in your list, then stop. Do not invent semantics.

## Final message

At most 300 words: state (done / gate reached / blocked), commits, test result lines, open requests. Details go
in the status file.
