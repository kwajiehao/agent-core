# Core Workflow

The user points you to a task file: "implement agent-docs/tasks/<name>.md".
Read the task's `read_first` files, then implement within its `allowed_paths`.

## Workflow for every task

1. Read `read_first` files and the task doc
2. Identify the exact failing behavior, the narrowest owner function, and the smallest contract-preserving fix
3. Implement code + unit tests (red-green TDD)
4. Run `test_commands` from the task frontmatter
5. Write a smoke test script to `agent-docs/smoke-tests/<task-file-stem>.sh`
6. Start the local stack (see the repo's `agent-docs/TESTING.md` and `agent-docs/loop.yaml`) and run the smoke script against it
7. Stop anything you started
8. Run the simplify pass:
   - If you are Claude Code, run `/simplify`
   - If you are not Claude Code, run `claude -p "/simplify" --output-format stream-json --include-partial-messages`

Steps 5–7 are **mandatory**. The task is not done until the smoke test script
exists and passes. See [TESTING.md](TESTING.md) for smoke test conventions and
the repo's `agent-docs/TESTING.md` for stack setup.

## Generate missing verification

The loop owns its own verification. If a task doc arrives without
`test_commands`, acceptance criteria, or a smoke script path:

- Derive acceptance criteria from the observed behavior the task describes,
  and record them in the task doc before implementing.
- Add `test_commands` that run the tests you will write.
- The smoke script is always agent-authored; the task doc never contains it,
  only its path.

A task you cannot state verification for is a task you do not understand yet —
stop and clarify before writing code.

## Simplicity-first workflow

Start with the smallest change that fixes the observed behavior.

Before implementation, write down or hold in mind:
- the exact failing behavior
- the narrowest owner function
- the smallest fix that preserves existing contracts

Prefer preserving existing interfaces. If a proposed fix adds parameters,
changes return types, or creates multiple new helpers, first check whether the
edge case can be internalized behind an existing function.

Prefer existing repo fixtures and assets over generated fixtures when
reproducing media, network, or API behavior.

## How to figure out what's done

Check code and git history, not status docs: list the modules that exist and
read `git log` for the paths the task touches. Task docs record intent; the
worktree records reality.

## Task registry

Task files in `agent-docs/tasks/` are the single source of truth.

## Error recovery

If blocked for more than 2 attempts at the same issue, update the task's
Handoff section with commands run, failures seen, and next hypothesis. Then stop.
