# Agent Core

A small repo-agnostic task runner for agentic coding.

It has one job: turn a task doc into a run directory, then verify that the
result stayed in scope and passed the commands declared by the task.

## Flow

```text
task.md -> prompt.md -> coordinator/maker/reviewer work
  -> runner verifies artifacts + diff + tests + optional smoke
```

The runner does not manage agents, start services, infer smoke scripts, or
accept self-reported results. Repo-specific setup belongs in the task's own
commands. The runner can require coordination artifacts, but the coordinator
invokes and manages any subagents.

## Task Schema

Task files are markdown files with YAML frontmatter:

```yaml
---
id: PR-12
title: Fix search pagination
read_first:
  - README.md
allowed_paths:
  - src/search/**
  - tests/search/**
test_commands:
  - pytest tests/search/test_pagination.py
coordination:
  mode: review
  reviewer:
    characterization: >
      Principal search-platform reviewer focused on pagination correctness and
      regression coverage.
smoke_command: ./scripts/smoke-search.sh   # optional
---
```

Required fields:

- `id`
- `title`
- `allowed_paths`
- `test_commands`

Optional fields:

- `read_first`
- `coordination`
- `smoke_command`

`test_commands` must contain at least one command for verification to pass.

`coordination.mode` defaults to `solo` and can be:

- `solo`: the coordinator may implement directly. No subagent artifact is
  required.
- `review`: the coordinator may implement directly, but final verification
  requires `subagents/reviewer.md` with `Verdict: approve`.
- `delegated`: final verification requires `subagents/maker.md` and
  `subagents/reviewer.md` with `Verdict: approve`.

When `mode` is `review`, set `coordination.reviewer.characterization`. When
`mode` is `delegated`, set both `coordination.maker.characterization` and
`coordination.reviewer.characterization`. These characterizations are
task-specific role frames for subagent invocation, for example the relevant
domain, system type, scale, language, or review specialty.

## How To Use

The intended human interface is the repo-local skill:

```text
Use the agent-docs-loop skill to set up and run a task in this repo.
```

Install the skill once from this repo:

```bash
python /path/to/agent-core/scripts/install_skills.py
```

This installs `skills/agent-docs-loop` into
`${CODEX_HOME:-~/.codex}/skills/agent-docs-loop`. Use `--force` to replace an
existing install, or `--dest <dir>` to install somewhere else.

After installation, start a new agent turn and ask it to use the skill. With
that prompt, the coding agent should ask what you want changed, ask which
coordination mode to use, propose the task doc, get your confirmation, generate
`agent-docs/`, then execute the task.

You should not need to run the CLI yourself for normal use. The CLI exists so
agents and scripts have a deterministic way to create task docs, prepare runs,
and verify outcomes.

The skill lives at:

```text
skills/agent-docs-loop/SKILL.md
```

Install or expose that skill to your coding agent, then start with a normal
request such as:

```text
Use agent-docs-loop. I want to fix search pagination in this repo.
```

The agent should:

1. Ask enough questions to understand the task and coordination mode.
2. Inspect the repo and propose `allowed_paths`, `read_first`,
   `test_commands`, and optional `smoke_command`.
3. Ask you to confirm the proposed task doc.
4. Generate the task doc after confirmation.
5. Clear context if the client supports it, or restart from the generated task
   doc and prompt.
6. Run the prepare/edit/verify loop and report the runner artifacts.

The runner never spawns agents. It gives the coding agent a prompt, records run
artifacts, and verifies the declared contract.

### Verification Commands

Verification commands and smoke tests are not generated automatically by the
runner. The task must declare at least one `test_commands` entry, and the runner
executes exactly those commands. `smoke_command` is optional and runs only when
declared.

When you use the skill, the coding agent should infer and propose verification
commands from repo evidence such as README instructions, package scripts,
existing tests, CI config, or smoke scripts. If it cannot find a credible
command, it should ask you rather than inventing one.

## CLI Usage

Run from the consuming repo root, or pass `--repo-root`.

Generate a task:

```bash
uv --project /path/to/agent-core run python /path/to/agent-core/loop/run_task.py \
  --new-task PR-12 \
  --title "Fix search pagination" \
  --allowed-path 'src/search/**' \
  --allowed-path 'tests/search/**' \
  --test-command 'pytest tests/search/test_pagination.py' \
  --coordination-mode review \
  --reviewer-characterization 'Principal search-platform reviewer focused on pagination correctness.'
```

This creates:

```text
agent-docs/tasks/PR-12-fix-search-pagination.md
agent-docs/MEMORY.md
agent-docs/skills/README.md
```

Prepare a run for an agent:

```bash
uv --project /path/to/agent-core run python /path/to/agent-core/loop/run_task.py \
  agent-docs/tasks/<name>.md --prepare-run
```

This writes:

```text
agent-docs/runs/<task-id>/<run-id>/prompt.md
agent-docs/runs/<task-id>/<run-id>/run.json
agent-docs/runs/<task-id>/<run-id>/handoff.md
agent-docs/runs/<task-id>/<run-id>/subagents/README.md
```

After the agent edits the repo:

```bash
uv --project /path/to/agent-core run python /path/to/agent-core/loop/run_task.py \
  agent-docs/tasks/<name>.md \
  --verify-only --run-dir agent-docs/runs/<task-id>/<run-id>
```

Verification writes:

```text
coordination.json
tests.json
smoke.json
verification.json
```

Each run also has a `handoff.md` file for durable notes while work is in
progress.

The CLI exits `0` when verification status is `passed`, `1` when gates fail,
and `2` when the task/frontmatter is invalid.

## What Is Enforced

- Changed files, excluding pre-existing dirty files captured at prepare time,
  must match `allowed_paths`.
- `coordination.mode` must have its required subagent artifacts, when configured.
- Every `test_commands` command must pass.
- `smoke_command`, when present, must pass.

Everything else is normal agent judgment.

## Optional Agent Practices

### Roles

The main agent is the coordinator. It owns the run, reads the task contract,
invokes required subagents, integrates accepted findings, runs the task
commands, and runs final verification.

The other roles are:

- Maker: implements a bounded change inside assigned paths. For small `solo` or
  `review` tasks, the coordinator may act as maker. For `delegated` tasks, use
  a maker subagent and record its brief/result in `subagents/maker.md`.
- Reviewer: independently reviews the diff, tests, and artifacts. It does not
  edit by default and records findings plus `Verdict: approve` or a requested
  change in `subagents/reviewer.md`.
- Verifier: the runner's deterministic gates. The runner remains the only
  acceptance source.
- Reflector: an optional post-pass check that persists reusable lessons into
  repo memory or a repo-local skill.

Keep agent roles as operating practices. The runner only enforces declared
artifacts and commands.

### Subagents

Subagents are useful for isolated implementation attempts, independent review,
research, or domain-specific investigation. They are invoked by the coordinator,
not by the runner.

The coordinator should invoke a subagent when one of these is true:

- the task asks for independent review, research, or a second implementation
  attempt
- a repo-local skill or `AGENTS.md` says a specialized agent should handle that
  kind of work
- the task has separable investigation and implementation threads
- the coordinator is stuck and needs a focused hypothesis checked
- the change is risky enough that an independent reviewer is worth the extra
  time

When using a subagent, pass it the task doc, `prompt.md`, relevant `read_first`
files, `allowed_paths`, current run artifacts, and the task-specific role
characterization from `coordination`. The coordinator remains responsible for
final edits and runner verification.

Each run contains:

```text
agent-docs/runs/<task-id>/<run-id>/subagents/
```

Use that directory for subagent briefs and findings. The coordinator should
summarize accepted findings back into `handoff.md`.

### Skills

Repo-local skills can live under:

```text
agent-docs/skills/<skill-name>/SKILL.md
```

The simplified runner does not auto-discover or inject skills. Reference useful
skills from `AGENTS.md`, the task body, or `read_first` when they matter.

### Reflection

Reflection is useful after a passed run, but it is not an acceptance gate. A
simple reflection pass should ask:

- Did this run reveal reusable repo knowledge?
- Should that knowledge go in `agent-docs/MEMORY.md`, a repo-local skill, or
  nowhere?
- Did the task template or docs need clarification?

Only persist lessons that are likely to help future tasks.

### Memory

Use two levels of memory:

- Run memory: `agent-docs/runs/<task-id>/<run-id>/handoff.md` plus JSON command
  artifacts. This is for resuming interrupted work.
- Subagent memory: `agent-docs/runs/<task-id>/<run-id>/subagents/*.md`. This is
  for scoped briefs, findings, evidence, and recommendations from subagents.
- Repo memory: `agent-docs/MEMORY.md` or repo-local skills. This is for durable
  lessons that apply across tasks.

## Agent Guidance

- [CODING.md](/Users/kwa/Documents/personal/agent-core/CODING.md) describes
  implementation principles.
- [TESTING.md](/Users/kwa/Documents/personal/agent-core/TESTING.md) describes
  regression and smoke-test conventions.
