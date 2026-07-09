---
id: PR-XX
title: <title>
read_first:
  - README.md
allowed_paths:
  - <source dir>/**
  - <test dir>/**
test_commands:
  - <command that verifies this task>
# coordination:
#   mode: solo | review | delegated
#   maker:
#     characterization: <required for delegated; task-specific maker expertise>
#   reviewer:
#     characterization: <required for review/delegated; task-specific review expertise>
# smoke_command: <optional end-to-end command>
---

# PR-XX: <title>

## Task

<What should change?>

## Acceptance

1. <Observable condition>
2. `test_commands` pass.
3. `smoke_command` passes, if defined.
4. Required coordination artifacts pass, if `coordination.mode` is `review` or
   `delegated`.

## Handoff

<Commands run, failures seen, next hypothesis, and partial progress when
stopping before completion.>
