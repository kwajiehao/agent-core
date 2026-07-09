---
name: agent-docs-loop
description: Use when a user wants a coding agent to create, intake, or run an agent-docs task through the simplified run_task.py loop, including asking what to build, choosing solo/review/delegated coordination, generating and confirming the task doc, then executing prepare/edit/simplify/review/verify.
---

# Agent-Docs Loop

Use this skill in either mode:

- No task doc yet: run intake, create the task doc, confirm it with the user,
  then execute it.
- Task doc already exists: prepare, edit, simplify, review, and verify that
  task.

## Intake Mode

When the user asks to start work but has not provided an
`agent-docs/tasks/<name>.md` file:

1. Ask the user what they want changed and which coordination mode to use. If
   the user is unsure, recommend:
   - `solo` for narrow, low-risk changes.
   - `review` for ambiguous, user-facing, shared, or risky changes.
   - `delegated` when implementation should be done by a maker subagent before
     independent review.
2. Inspect the repo before drafting the task. Find likely context docs, allowed
   paths, package/test commands, and existing smoke scripts.
3. Propose a task summary to the user with:
   - task id and title
   - `read_first`
   - `allowed_paths`
   - `test_commands`
   - optional `smoke_command`
   - `coordination.mode`
   - required maker/reviewer characterizations
4. Ask for explicit confirmation before creating the task doc.
5. Create the task with:
   ```bash
   uv --project <agent-core> run python <agent-core>/loop/run_task.py --repo-root <target-repo> \
     --new-task <id> \
     --title <title> \
     --allowed-path <glob> \
     --test-command <command> \
     --coordination-mode <solo|review|delegated> \
     [--read-first <path>] \
     [--maker-characterization <text>] \
     [--reviewer-characterization <text>] \
     [--smoke-command <command>]
   ```
6. Open the generated task doc, replace placeholder Task and Acceptance text
   with the confirmed request, then show the task path to the user.
7. Reset context if the client supports it. If not, simulate a reset: ignore
   intake discussion, read only the generated task doc, generated `prompt.md`,
   and `read_first` files before editing.
8. Execute the task using Execution Mode.

Run the command from any working directory. `--project <agent-core>` ensures
the runner uses agent-core's dependencies. If `<agent-core>/loop/run_task.py` is
not available in the workspace or known from the skill installation, ask the
user for the agent-core path.

## Verification Command Policy

The runner does not infer verification commands or smoke tests. It only executes
the `test_commands` and optional `smoke_command` declared in the task. During
intake, propose commands from repo evidence such as README instructions,
`pyproject.toml`, package scripts, existing test files, CI config, or smoke
scripts. Do not invent a smoke command unless the task will create that script
inside `allowed_paths`. If no credible command is discoverable, ask the user.

`test_commands` must contain at least one command. `smoke_command` is optional
and should be included only when it gives meaningful integration or user-facing
coverage beyond the tests.

## Execution Mode

Use this when the user asks to implement an `agent-docs/tasks/<name>.md` task.

1. Prepare a run:
   ```bash
   uv --project <agent-core> run python <agent-core>/loop/run_task.py agent-docs/tasks/<name>.md --repo-root <target-repo> --prepare-run
   ```
2. Read the generated `prompt.md`, the task doc, every `read_first` file,
   `CODING.md`, and `TESTING.md`.
3. Follow the generated `coordination.mode`:
   - `solo`: the coordinator may implement directly.
   - `review`: the coordinator may implement directly; reviewer approval is
     required after the simplify pass.
   - `delegated`: the coordinator must invoke a maker; reviewer approval is
     required after the simplify pass.
4. Run the simplify pass after implementation and before required review:
   - In Claude Code: `/simplify`
   - Outside Claude Code:
     ```bash
     claude --model opus-4.8 -p "/simplify" --output-format stream-json --include-partial-messages
     ```
   If the simplify pass changes files, include those changes in the review and
   final verification.
5. Run the task's `test_commands` and optional `smoke_command`.
6. Verify with the runner:
   ```bash
   uv --project <agent-core> run python <agent-core>/loop/run_task.py agent-docs/tasks/<name>.md --repo-root <target-repo> --verify-only --run-dir <run-dir>
   ```

Do not treat agent summaries as verification. Use the runner artifacts as the
source of truth.

Role mapping in the simplified loop:

- Coordinator: the main agent that owns the run, invokes required subagents,
  integrates findings, and runs final verification.
- Maker: implements a bounded patch inside assigned paths. The coordinator may
  act as maker for `solo` and `review`; `delegated` requires a maker subagent.
- Reviewer: independently reviews the diff, tests, and artifacts, then records
  findings and an exact `Verdict: approve` line when satisfied.
- Verifier: the runner gates.
- Reflector: optional post-pass memory/skill update after runner verification
  passes.

Invoke subagents when required by `coordination.mode`, when the task requests
review/research, when repo instructions call for a specialized skill, when work
can split cleanly, when the main path is stuck, or when risk justifies
independent review. Subagents and repo-local skills do not change the task's
`allowed_paths` or acceptance commands.

Keep resume notes in the run's `handoff.md`. Keep subagent briefs and findings
in the run's `subagents/` directory, then summarize accepted findings back into
`handoff.md`. After a passed run, reflect only reusable lessons into repo memory
or a repo-local skill.
