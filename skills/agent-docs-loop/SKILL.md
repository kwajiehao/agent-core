---
name: agent-docs-loop
description: Use when asked to run an agent-docs task through run_task.py, coordinating maker work, runner-owned verification, fresh verifier review, retry, and reflection.
---

# Agent-Docs Loop

Use this when the user says something like "run `run_task.py` for task X" or
"run the agent-docs loop for `agent-docs/tasks/<name>.md`".

## Role

You are the loop coordinator. Keep deterministic gates in `run_task.py`; use
agents for implementation judgment and independent review.

## Workflow

1. Read the agent-core `WORKFLOW.md`, this skill, and the task doc.
2. Prepare a run:
   ```bash
   python <agent-core>/loop/run_task.py agent-docs/tasks/<name>.md --prepare-run
   ```
3. Read the generated `maker-prompt.md` and the `agent-docs-maker` skill.
4. Act as the maker, or delegate to a maker subagent when available.
5. After maker work, run runner-owned verification (export the API key env var
   named in `agent-docs/loop.yaml` first, if the repo configures one):
   ```bash
   python <agent-core>/loop/run_task.py agent-docs/tasks/<name>.md --verify-only --run-dir <run-dir>
   ```
6. If verification fails, give the maker the failing gate artifacts and retry within the task guardrails.
7. If verification returns `needs_verifier`, use a fresh verifier pass with `verifier-prompt.md` and the `agent-docs-verifier` skill.
8. If the verifier returns `accepted`, run reflection using `reflection-prompt.md` and the `agent-docs-reflection` skill.

## Guardrails

- The maker cannot mark a task done.
- The verifier cannot override failed runner gates.
- `--skip-smoke` is diagnostic only; it can never produce acceptance.
- Do not paste or persist API keys in run artifacts or task docs.
- If blocked for more than 2 attempts at the same issue, update the task Handoff and stop.
