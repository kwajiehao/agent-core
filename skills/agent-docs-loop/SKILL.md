---
name: agent-docs-loop
description: Use when asked to run an agent-docs task through the simplified run_task.py prepare/verify loop.
---

# Agent-Docs Loop

Use this when the user asks to implement an `agent-docs/tasks/<name>.md` task.

1. Prepare a run:
   ```bash
   python <agent-core>/loop/run_task.py agent-docs/tasks/<name>.md --prepare-run
   ```
2. Read the generated `prompt.md`, the task doc, every `read_first` file,
   `CODING.md`, and `TESTING.md`.
3. Implement the smallest correct change inside `allowed_paths`.
4. Run the task's `test_commands` and optional `smoke_command`.
5. Verify with the runner:
   ```bash
   python <agent-core>/loop/run_task.py agent-docs/tasks/<name>.md --verify-only --run-dir <run-dir>
   ```

Do not treat agent summaries as verification. Use the runner artifacts as the
source of truth.

Role mapping in the simplified loop:

- Maker: the main agent implementing the task.
- Verifier: the runner gates, with an optional reviewer subagent when useful.
- Reflector: optional post-pass memory/skill update after runner verification
  passes.

Invoke subagents when the task requests review/research, repo instructions call
for a specialized skill, work can split cleanly, the main path is stuck, or risk
justifies independent review. Subagents and repo-local skills do not change the
task's `allowed_paths` or acceptance commands.

Keep resume notes in the run's `handoff.md`. Keep subagent briefs and findings
in the run's `subagents/` directory, then summarize accepted findings back into
`handoff.md`. After a passed run, reflect only reusable lessons into repo memory
or a repo-local skill.
