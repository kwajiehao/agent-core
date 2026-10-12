# Workflow reliability verification — 2026-10-11

Implementation starts from `7933c47f6e06426228f5c97bc27d2042d0603e78`.
No commits in either source repository, pushes or personal/global skill
installation are part of this task. Isolated Git fixtures create local baselines.

## Red-green evidence

- `runner-red.txt`: 21 failing regressions against the original runner, one
  passing preservation control. Cases cover dirty/committed/command-created
  scope, unbound/stale evidence, task mutation, timeout descendants and output.
- Follow-up red logs record corrupt HEAD objects, malformed contracts/artifacts
  and discovery selecting an obsolete legacy attempt after a newer pass.
- `relative-paths-red.txt` / `relative-paths-green.txt` capture a forward-pilot
  discovery: explicit repository roots now anchor relative task/run paths for
  preparation, review sealing and verification from a different working directory.
- `runner-green.txt`: development full-suite result after those corrections.
- `installers-red.json`: original installer failures in both repositories.
  The current installer tests additionally verify that replacement does not
  follow symlinks into foreign files/directories.

The final authoritative suite execution and exact task/tree/review bindings are
in the fresh v2 task run's `verification.json`. The earlier v1 preparation is
retained as history, not retroactively represented as a v2 baseline. Independent
review must inspect the complete delta from the initial HEAD, since a fresh
baseline alone does not prove the preceding implementation stayed in scope.

## Behavioral evidence

Independent isolated agent trials and assessor checks are retained in the sibling
`agent-skills/agent-docs/verification/workflow-reliability-20261011` directory.
The core trials exercise preserving initial dirty work and discovering a verifier
that observes persistence across fresh processes. They pin a frozen skill/runner
copy. Synthetic controls and ordinary unit tests are not agent executions.
Two initial Python pilots exposed incidental bytecode writes. A small verification
profile correction explains prevention/owned outputs; a later clean-intake pilot
used `-B` without the bytecode scope failure. It discovered the relative-path issue
above. Frozen pilot runner copies precede that subsequently tested CLI correction.

Final-answer-only agent traces cannot establish complete interaction counts,
tokens, latency, or an accepted-without-correction rate. These measurements stay
unknown; artifact correctness is assessed separately. Do not infer broad
efficiency improvements from the small pilot bank.

## Boundaries

Scope is tracked and nonignored untracked Git-visible files, not a sandbox for
ignored outputs or external systems. Task/code/review binding proves freshness,
not reviewer independence or semantic completeness. Commands run on POSIX with
64 KiB retained per stdout/stderr; timeout is incomplete execution.
