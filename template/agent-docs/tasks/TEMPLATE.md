---
id: PR-XX
title: <title>
status: todo
owner: ""                   # agent/person currently working on it
last_updated: ""            # ISO date
read_first:
  - agent-docs/TESTING.md
allowed_paths:
  - <source dir the task may touch>/**
  - <test dir for the task>/**
  - agent-docs/smoke-tests/**
test_commands:
  - <command that runs this task's tests>
rollback: <how to undo this change>
# loop:                     # optional per-task overrides
#   max_attempts: 3
#   skills: [<repo-local skill names to inject>]
---

# PR-XX: <title>

## What to Build
<1-2 sentences>

## Models
<request/response or data model signatures, if applicable>

## Reuse These
- `path/to/file:Symbol` — what it does

## Acceptance Criteria
1. <verifiable condition>
2. Unit tests pass (see frontmatter `test_commands`)
3. Smoke test script written to `agent-docs/smoke-tests/PR-XX-<name>.sh` and passes against the local stack (see TESTING.md)

## Cannot Verify
<anything needing manual testing — leave blank if none>

## Handoff
<Mutable section. Agent writes here when stopping or handing off:
commands run, failures seen, next hypothesis, partial progress.>
