# Agent Core

A small repo-agnostic task runner for agentic coding.

It has one job: turn a task doc into a run directory, then verify that the
result stayed in scope and passed the commands declared by the task.

## Quick Start

From this checkout, install the agent-facing skill once:

```bash
python scripts/install_skills.py --force
```

Then start a fresh agent conversation and provide the target repository:

```text
Use agent-docs-loop for /path/to/target-repo.
```

Agent Core will resume unfinished work, recover the latest completed context,
or guide you through creating a new task. To start new work immediately, append
`Create a new task for: <request>.` See [How To Use](#how-to-use) for details.

## Roles

Agent Core separates agent orchestration from deterministic verification.

- Operator: the human who starts an agent turn, confirms task setup, and
  provides missing context when needed.
- Coordinator: the main coding agent session invoked by the operator. It owns
  the run, reads the task contract, implements directly or invokes required
  subagents, integrates findings, runs commands, and fixes failures.
- Maker: the implementation responsibility. In `solo` and `review` mode, the
  coordinator may act as maker; in `delegated` mode, this must be a subagent
  with findings recorded in `subagents/maker.md`.
- Reviewer: the independent quality and risk reviewer. It reviews the diff,
  tests, and artifacts, then records findings and `Verdict: approve` when
  satisfied. It is not the acceptance source.
- Runner: the `loop/run_task.py` harness. It prepares run artifacts and
  performs deterministic verification of allowed paths, required coordination
  artifacts, declared tests, and optional smoke commands. It does not launch
  agents, choose fixes, or accept self-reported results.
- Reflector: an optional post-pass responsibility that stores reusable lessons
  in repo memory or skills after runner verification passes.

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
Use agent-docs-loop for /path/to/target-repo.
```

Install the skill once from this repo:

```bash
python /path/to/agent-core/scripts/install_skills.py
```

This installs `skills/agent-docs-loop` into
`${CODEX_HOME:-~/.codex}/skills/agent-docs-loop` for Codex. It also installs a
Claude copy at `${CLAUDE_HOME:-~/.claude}/skills/agent-docs-loop` and a Claude
slash-command adapter at `${CLAUDE_HOME:-~/.claude}/commands/agent-docs-loop.md`.
Use `--force` to replace existing installs, `--codex-dest <dir>` to change the
Codex destination, or `--claude-dir <dir>` to change the Claude destination.

After installation, start a new agent turn from the Agent Core checkout and
provide only the target repository directory. The skill first discovers the
repository's run state:

- An unfinished or failed run is resumed from its existing task, prompt,
  handoff, and verification artifacts.
- If every run passed, the newest completed run is loaded as prior context
  before the agent handles a new request.
- If no valid run exists, the agent starts task intake and asks what to build.

Malformed, missing, inconsistent, or repository-escaping artifacts are skipped
and reported as warnings instead of being trusted.

You should not need to run the CLI yourself for normal use. The CLI exists so
agents and scripts have a deterministic way to create task docs, prepare runs,
and verify outcomes.

To resume or recover context, the repository directory is the entire request:

```text
Use agent-docs-loop for /Users/me/code/my-repo.
```

For a brand-new repository, you can include the requested change in that first
message or answer the skill's intake question. The installed skill handles
discovery, intake, confirmation, task generation, and execution using the
workflow in `WORKFLOW.md`.

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

Discover the run to resume from any working directory:

```bash
uv --project /path/to/agent-core run python /path/to/agent-core/loop/run_task.py \
  --repo-root /path/to/target-repo --resume
```

The command emits JSON. `action` is `resume` for the newest run without passing
verification, `completed_context` for the newest run when all valid runs passed,
or `intake_required` when no valid run exists. The result includes resolved task,
run, prompt, handoff, and verification paths plus verification status and any
warnings. Resume discovery never creates a new run.

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

The CLI exits `0` for resume discovery and when verification status is `passed`,
`1` when verification gates fail, and `2` when the task/frontmatter is invalid.

## What Is Enforced

- Changed files, excluding pre-existing dirty files captured at prepare time,
  must match `allowed_paths`.
- `coordination.mode` must have its required subagent artifacts, when configured.
- Every `test_commands` command must pass.
- `smoke_command`, when present, must pass.

Everything else is normal agent judgment. Agent execution details live in
`WORKFLOW.md`.

## Agent Docs

- [WORKFLOW.md](/Users/kwa/Documents/personal/agent-core/WORKFLOW.md) describes
  the task execution loop.
- [CODING.md](/Users/kwa/Documents/personal/agent-core/CODING.md) describes
  implementation principles.
- [TESTING.md](/Users/kwa/Documents/personal/agent-core/TESTING.md) describes
  regression and smoke-test conventions.
