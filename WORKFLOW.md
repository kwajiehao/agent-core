# Workflow

This is the canonical task execution guide for agents. The runner verifies
artifacts and commands; the main agent coordinates the work.

When asked to work from an `agent-docs/tasks/<name>.md` file:

1. Run `loop/run_task.py <task> --prepare-run`.
2. Read the generated `prompt.md`, the task doc, and every `read_first` file.
3. Read `CODING.md` and `TESTING.md` when making implementation or test choices.
4. Check `coordination.mode` in the generated prompt:
   - `solo`: the coordinator may make the smallest correct change directly.
   - `review`: the coordinator may make the change, then must invoke a reviewer.
   - `delegated`: the coordinator must invoke a maker and then a reviewer.
5. Run the simplify pass after implementation and before required review:
   - In Claude Code: `/simplify`
   - Outside Claude Code:
     `claude --model opus-4.8 -p "/simplify" --output-format stream-json --include-partial-messages`
6. Store required briefs and findings in `subagents/`:
   - `review` requires `subagents/reviewer.md` with `Verdict: approve`.
   - `delegated` requires `subagents/maker.md` and `subagents/reviewer.md`
     with `Verdict: approve`.
7. Run the task's `test_commands`.
8. Run `smoke_command` if the task defines one.
9. Run `loop/run_task.py <task> --verify-only --run-dir <run-dir>`.
10. Update `handoff.md` if stopping before completion.
11. After a passed run, optionally reflect into repo memory or a repo-local skill
   only when the lesson is reusable.

The main agent is the coordinator. It may also act as maker for `solo` and
`review` tasks. The runner is the required verifier; reviewer subagents provide
independent judgment but are not the acceptance source. Reflection is optional
after runner verification passes.

If verification fails, use `verification.json`, `coordination.json`,
`tests.json`, and `smoke.json` as the source of truth. Fix the issue or update
the task handoff with the commands run, failures seen, and next hypothesis.

## Responsibilities

- Coordinator: owns the run, reads the task contract, invokes required
  subagents, integrates accepted findings, runs the task commands, and runs
  final verification.
- Maker: implements a bounded change inside assigned paths. For small `solo` or
  `review` tasks, the coordinator may act as maker. For `delegated` tasks, use
  a maker subagent and record its brief/result in `subagents/maker.md`.
- Reviewer: independently reviews the diff, tests, and artifacts. It does not
  edit by default and records findings plus `Verdict: approve` or a requested
  change in `subagents/reviewer.md`.
- Verifier: the runner's deterministic gates. The runner remains the only
  acceptance source.
- Reflector: an optional post-pass check that persists reusable lessons into
  repo memory or a repo-local skill after runner verification passes.

## Subagents

Subagents are invoked by the coordinator, not by the runner. Invoke one when the
task requires it, asks for review or research, has separable investigation and
implementation threads, needs a specialized skill, leaves the coordinator
stuck, or carries enough risk to justify independent review.

When using a subagent, pass it the task doc, `prompt.md`, relevant `read_first`
files, `allowed_paths`, current run artifacts, and the task-specific role
characterization from `coordination`. The coordinator remains responsible for
final edits and runner verification.

Store subagent briefs and findings in:

```text
agent-docs/runs/<task-id>/<run-id>/subagents/
```

Summarize accepted findings back into `handoff.md`.

## Memory And Reflection

Use run memory for interrupted work: `handoff.md`, JSON command artifacts, and
`subagents/*.md`.

Use repo memory for durable lessons: `agent-docs/MEMORY.md` or repo-local
skills under `agent-docs/skills/<skill-name>/SKILL.md`.

Reflect only after a passed run. Persist a lesson when it is likely to help
future tasks; otherwise leave it in the run artifacts.
