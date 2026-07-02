# Agent Core

A repo-agnostic task loop for autonomous agentic coding. It turns a task doc
with machine-readable guardrails into a controlled maker → runner-verification
→ verifier → reflection workflow, where the loop authors its own regression
tests and smoke tests and final acceptance is tied to runner-owned evidence,
not agent self-reports.

## The loop

```
task doc ──► maker (TDD, writes smoke test) ──► runner gates (diff scope,
tests, smoke against live stack) ──► fresh verifier ──► reflection (skills)
```

Three properties make it safe to run autonomously:

- **Guardrails are data.** Each task's frontmatter declares `allowed_paths`,
  `test_commands`, `read_first`, and `rollback`. The runner enforces them
  deterministically — the maker cannot widen its own scope.
- **The loop generates its own verification.** The maker must write a failing
  test before code and a smoke script exercising the live behavior. A task
  without verification is authored into one before implementation starts.
- **Acceptance is separated from implementation.** The maker cannot mark a
  task done; the verifier cannot override failed runner gates.

## Layout

| Path | Purpose |
|---|---|
| `WORKFLOW.md` | The core loop every task follows |
| `CODING.md` | General implementation principles |
| `TESTING.md` | General regression- and smoke-test conventions |
| `skills/` | Role skills: loop coordinator, maker, verifier, reflection |
| `loop/` | The runner: prepares run prompts, executes verification gates |
| `template/agent-docs/` | Skeleton to copy into a consuming repo |

## Adopting in a repo

1. Copy `template/agent-docs/` to `<repo>/agent-docs/`.
2. Fill in `agent-docs/TESTING.md` with repo specifics: local stack setup,
   how to run the dev server, connection details, sample fixtures.
3. Fill in `agent-docs/loop.yaml`: services the smoke gate must bring up and
   (optionally) the env var holding the API key smoke scripts receive.
4. Point the repo's `AGENTS.md`/`CLAUDE.md` at this repo's `WORKFLOW.md` and
   at the repo-local `agent-docs/TESTING.md`.
5. Write tasks from `agent-docs/tasks/TEMPLATE.md`.

The repo-specific layer lives entirely in the consuming repo; this repo holds
only what is true everywhere.

## Running the loop

```bash
# Prepare a run (writes maker/verifier/reflection prompts + run.json)
python /path/to/agent-core/loop/run_task.py agent-docs/tasks/<name>.md --prepare-run

# Verify a run (diff scope, test commands, smoke against the live stack)
python /path/to/agent-core/loop/run_task.py agent-docs/tasks/<name>.md \
  --verify-only --run-dir agent-docs/runs/<task-id>/<run-id>
```

Run both from the consuming repo's root (or pass `--repo-root`). Artifacts
land in `<repo>/agent-docs/runs/<task-id>/<run-id>/`.

## Agent compatibility

Role skills use the `SKILL.md` + YAML frontmatter format, so they load
directly as Claude Code skills (symlink `skills/*` into `.claude/skills/` or
reference them by path). The coordinator skill is idempotent per task and
resumes from run artifacts, so it can be driven by recurring invocation (e.g.
Claude Code's `/loop`) or by any agent that can run shell commands.

## Extension points

- `agent-docs/TESTING.md` — repo setup, dev server, fixtures.
- `agent-docs/loop.yaml` — services + API key env for the smoke gate.
- `agent-docs/skills/` — repo-local skills; the runner injects keyword-matched
  skills into maker/verifier prompts. A repo-local skill with the same name as
  a role skill overrides it.
- Task frontmatter `loop:` block — per-task attempt budgets and explicit skills.
