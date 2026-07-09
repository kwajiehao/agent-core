# Workflow

When asked to work from an `agent-docs/tasks/<name>.md` file:

1. Run `loop/run_task.py <task> --prepare-run`.
2. Read the generated `prompt.md`, the task doc, and every `read_first` file.
3. Read `CODING.md` and `TESTING.md` when making implementation or test choices.
4. Make the smallest correct change inside `allowed_paths`.
5. Use subagents only when the task, repo instructions, or risk/stuckness makes
   a focused second agent useful; store briefs and findings in `subagents/`.
6. Run the task's `test_commands`.
7. Run `smoke_command` if the task defines one.
8. Run `loop/run_task.py <task> --verify-only --run-dir <run-dir>`.
9. Update `handoff.md` if stopping before completion.
10. After a passed run, optionally reflect into repo memory or a repo-local skill
   only when the lesson is reusable.

The main agent is the maker. The runner is the required verifier; an
independent reviewer subagent is optional. Reflection is optional after runner
verification passes.

If verification fails, use `verification.json`, `tests.json`, and `smoke.json`
as the source of truth. Fix the issue or update the task handoff with the
commands run, failures seen, and next hypothesis.
