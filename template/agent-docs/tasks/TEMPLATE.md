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
# smoke_command: <optional end-to-end command>
---

# PR-XX: <title>

## Task

<What should change?>

## Acceptance

1. <Observable condition>
2. `test_commands` pass.
3. `smoke_command` passes, if defined.

## Handoff

<Commands run, failures seen, next hypothesis, and partial progress when
stopping before completion.>
