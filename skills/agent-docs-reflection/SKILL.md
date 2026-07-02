---
name: agent-docs-reflection
description: Use after an accepted agent-docs loop run to decide whether to create or update repo-local skills from repeated or hard workflow knowledge.
---

# Agent-Docs Reflection

Use this only after runner-owned gates pass and the verifier returns `accepted`.

## Goal

Capture reusable process knowledge without turning one-off mistakes into
permanent instructions.

## Create Or Update A Skill When

- The accepted run repeated a workflow seen before.
- The task involved fragile external setup, smoke testing, or multi-repo coordination.
- The verifier caught a reusable failure mode.
- The maker needed more than one attempt for a reason future agents can avoid.

## Do Not Create A Skill When

- The lesson is task-specific and unlikely to repeat.
- The run was failed or blocked.
- The knowledge belongs in the task doc, not a reusable workflow.
- The proposed skill would duplicate the repo's `AGENTS.md`, its
  `agent-docs/TESTING.md`, or agent-core's `WORKFLOW.md`.

## Storage

Create repo-local skills under:

```text
agent-docs/skills/<skill-name>/SKILL.md
```

Promote a skill into agent-core's `skills/` only when it is useful across
repos and contains nothing repo-specific.

Keep `SKILL.md` concise. Put long examples in `references/` and deterministic
helpers in `scripts/`.
