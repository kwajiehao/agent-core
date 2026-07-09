# Workflow

When asked to work from an `agent-docs/tasks/<name>.md` file:

1. Run `loop/run_task.py <task> --prepare-run`.
2. Read the generated `prompt.md`, the task doc, and every `read_first` file.
3. Read `CODING.md` and `TESTING.md` when making implementation or test choices.
4. Check `coordination.mode` in the generated prompt:
   - `solo`: the coordinator may make the smallest correct change directly.
   - `review`: the coordinator may make the change, then must invoke a reviewer.
   - `delegated`: the coordinator must invoke a maker and then a reviewer.
5. Store required briefs and findings in `subagents/`:
   - `review` requires `subagents/reviewer.md` with `Verdict: approve`.
   - `delegated` requires `subagents/maker.md` and `subagents/reviewer.md`
     with `Verdict: approve`.
6. Run the task's `test_commands`.
7. Run `smoke_command` if the task defines one.
8. Run `loop/run_task.py <task> --verify-only --run-dir <run-dir>`.
9. Update `handoff.md` if stopping before completion.
10. After a passed run, optionally reflect into repo memory or a repo-local skill
   only when the lesson is reusable.

The main agent is the coordinator. It may also act as maker for `solo` and
`review` tasks. The runner is the required verifier; reviewer subagents provide
independent judgment but are not the acceptance source. Reflection is optional
after runner verification passes.

If verification fails, use `verification.json`, `coordination.json`,
`tests.json`, and `smoke.json` as the source of truth. Fix the issue or update
the task handoff with the commands run, failures seen, and next hypothesis.
