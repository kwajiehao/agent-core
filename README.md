# Agent Core

A small repo-agnostic task runner for agentic coding.

It has one job: turn a task doc into a run directory, then verify that the
result stayed in scope and passed the commands declared by the task.

## Flow

```text
task.md -> prompt.md -> agent edits -> runner verifies diff + tests + optional smoke
```

The runner does not manage agents, start services, infer smoke scripts, or
accept self-reported results. Repo-specific setup belongs in the task's own
commands.

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
- `smoke_command`

`test_commands` must contain at least one command for verification to pass.

## Usage

Run from the consuming repo root, or pass `--repo-root`.

```bash
python /path/to/agent-core/loop/run_task.py agent-docs/tasks/<name>.md --prepare-run
```

This writes:

```text
agent-docs/runs/<task-id>/<run-id>/prompt.md
agent-docs/runs/<task-id>/<run-id>/run.json
```

After the agent edits the repo:

```bash
python /path/to/agent-core/loop/run_task.py agent-docs/tasks/<name>.md \
  --verify-only --run-dir agent-docs/runs/<task-id>/<run-id>
```

Verification writes:

```text
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
- Every `test_commands` command must pass.
- `smoke_command`, when present, must pass.

Everything else is normal agent judgment.

## Optional Agent Practices

### Roles

The simplified runner does not create separate maker, verifier, or reflector
phases.

Those roles still exist as lightweight agent responsibilities:

- Maker: the main agent implementing the task.
- Verifier: the runner's deterministic gates, plus an optional independent
  reviewer subagent when the change is risky or ambiguous.
- Reflector: an optional post-pass check that persists reusable lessons into
  repo memory or a repo-local skill.

Keep these roles as practices, not required artifacts. The only acceptance
source is runner verification.

### Subagents

Subagents are useful for isolated implementation attempts, independent review,
research, or domain-specific investigation. They are not part of the runner's
contract.

The main agent should invoke a subagent when one of these is true:

- the task asks for independent review, research, or a second implementation
  attempt
- a repo-local skill or `AGENTS.md` says a specialized agent should handle that
  kind of work
- the task has separable investigation and implementation threads
- the main agent is stuck and needs a focused hypothesis checked
- the change is risky enough that an independent reviewer is worth the extra
  time

When using a subagent, pass it the task doc, `prompt.md`, relevant `read_first`
files, `allowed_paths`, and current run artifacts. The parent agent remains
responsible for final edits and runner verification.

Each run contains:

```text
agent-docs/runs/<task-id>/<run-id>/subagents/
```

Use that directory for subagent briefs and findings. The parent agent should
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
