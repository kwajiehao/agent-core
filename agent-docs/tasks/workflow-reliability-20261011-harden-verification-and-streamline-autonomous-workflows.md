---
id: "workflow-reliability-20261011"
title: "Harden verification and streamline autonomous workflows"
allowed_paths:
  - "loop/**"
  - "scripts/**"
  - "tests/**"
  - "skills/**"
  - "template/**"
  - "*.md"
  - ".gitignore"
  - "agent-docs/**"
test_commands:
  - "/private/tmp/agent-workflow-dev-20261011/bin/python -m pytest -q"
smoke_command: "/private/tmp/agent-workflow-dev-20261011/bin/python ../agent-skills/evals/run_evals.py verify ../agent-skills/agent-docs/verification/workflow-reliability-20261011/pilots --require-scenario core-clear-autonomy --require-scenario core-dirty-worktree --require-scenario core-runtime-verifier"
acceptance:
  - condition: "Scope checks include committed, initially dirty, and command-created changes; invalid Git state fails closed."
    command: "/private/tmp/agent-workflow-dev-20261011/bin/python -m pytest -q"
  - condition: "Task, review, acceptance and verification evidence are bound to current content and stale evidence cannot pass."
    command: "/private/tmp/agent-workflow-dev-20261011/bin/python -m pytest -q"
  - condition: "Command timeouts clean owned descendants and retained output is bounded."
    command: "/private/tmp/agent-workflow-dev-20261011/bin/python -m pytest -q"
  - condition: "Portable skill installation preserves foreign entries and creates the documented discovery path."
    command: "/private/tmp/agent-workflow-dev-20261011/bin/python -m pytest -q"
  - condition: "Independent autonomous-intake, dirty-worktree and fresh-process persistence pilot observations retain valid hashed evidence."
    command: "/private/tmp/agent-workflow-dev-20261011/bin/python ../agent-skills/evals/run_evals.py verify ../agent-skills/agent-docs/verification/workflow-reliability-20261011/pilots --require-scenario core-clear-autonomy --require-scenario core-dirty-worktree --require-scenario core-runtime-verifier"
coordination:
  mode: review
  reviewer:
    characterization: "Independent reviewer of baseline scope, evidence freshness, command lifecycle, skill routing and acceptance proof"
---

# workflow-reliability-20261011: Harden verification and streamline autonomous workflows

## Task

Implement the improvements authorized after the October 9 evaluation: harden
scope and evidence freshness, map acceptance to observable checks, bound command
lifecycle and output, streamline authorized intake, remove mandatory external
simplifier/model coupling, make documentation and installation portable, route
task-specific evidence requirements, and evaluate realistic agent behavior.
Use failing regressions before fixes where possible. Preserve existing user work.
Do not commit, publish or change installed personal skills as part of this task.

## Acceptance

1. The mapped behaviors above have meaningful red-green regressions and actual
   command evidence. Real agent pilots exercise revised skill decisions.
2. `test_commands` pass.
3. `smoke_command` passes, if defined.
4. Required coordination artifacts pass, if `coordination.mode` is `review` or `delegated`.

## Handoff

Initial HEAD: 7933c47f6e06426228f5c97bc27d2042d0603e78. Initial worktree clean.
Development environment: /private/tmp/agent-workflow-dev-20261011 (pytest/PyYAML).
Keep original-run context if v2 verification requires a new prepared snapshot;
independently review the full original-HEAD diff rather than calling a later
baseline proof of the complete implementation delta.
