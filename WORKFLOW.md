# Workflow

The main agent owns the task; the runner prepares durable context and executes
deterministic gates. Use [agent-docs-loop](skills/agent-docs-loop/SKILL.md) for
the canonical agent procedure and
[task playbooks](skills/agent-docs-loop/references/playbooks.md) for evidence that
differs between bugs, features, refactors, performance and investigations.

## Intake and coordination

A clear authorized implementation request is sufficient to inspect the repository
and create its task. Infer allowed paths, commands and coordination mode. Ask only
for unavailable product meaning, consequential scope expansion or new authority.
Respect read-only requests and explicit new work; repository discovery must not
redirect them into an old implementation task.

Use solo for narrow, clear work; review when independent judgment adds useful
confidence; delegated when a separate maker benefits implementation. The
coordinator chooses the mode from evidence and explains it. Delegate bounded
ownership, preserve shared-write ordering and inspect actual outcomes.

Each acceptance condition names an observable behavior and maps to a declared
test/smoke command. When a verifier is missing, create and prove a small
project-native driver inside authorized paths using
[verification profiles](skills/agent-docs-loop/references/verification-profiles.md).

## Execution and evidence

Prepare a run, read its contract/context, then work in verifiable units. Use
red-green regression testing where practical. Simplify the implementation before
review: direct coordinator inspection is sufficient, and available simplifier
tools are optional. There is no required external CLI or pinned model.

For review/delegated tasks, obtain an independent reviewer of the current full
delta and behavior evidence. Record findings and an exact Verdict: approve line
in subagents/reviewer.md. Use --record-review on that task/run to bind the review
artifact to the exact task and repository snapshot. This records freshness; the
coordinator is still responsible for reviewer independence.

Run --verify-only once for final execution of the declared tests and optional
smoke command. Earlier focused tests support development; avoid an unconditional
duplicate final suite. Read all gates and command outcomes. Scope includes task
commits, changes to initially dirty files, and command-created edits among tracked
and nonignored untracked files. Ignored untracked outputs are outside this scope
check. A verification
command that changes the tested source invalidates the snapshot and requires
verification of the resulting tree; generated proof artifacts should live under
the run's own directory or a documented ignored output location.

The task, reviewer, acceptance evidence and code must still match their recorded
identities. A passing gate proves only the checks declared by that contract. The
coordinator verifies that every requested outcome has meaningful evidence.

## Resume and autonomous work

Repository discovery reads durable runs; it does not launch or manage agents.
Read task, prompt, handoff and verification when present. Preserve the original
run for resumable v2 work. Legacy run records remain useful historical context,
but cannot supply an exact v2 baseline; review their task and prepare a fresh v2
run explicitly. Surface any warnings and skipped records.

Recover the completed/pending boundary without repeating still-valid work. Check
freshness before trusting old results and inspect actual handles before assuming
a process or service is alive. Owned scratch resources and preserved evidence
have separate lifecycles. Timeout/interruption is incomplete execution.

For sustained work, name the exit predicate, scope and budget; checkpoint
meaningful decisions, failed hypotheses, command outcomes and resources in
handoff.md. Pivot when evidence refutes the premise. Keep the original outcome
and authorization boundary intact.

## Learning and handoff

Capture consequential failures and human corrections even when a run fails.
Route validated reusable lessons to the strongest practical mechanism: domain
types, lint, regression, canonical helper or runtime check. Repo memory is useful
for judgment that cannot be enforced structurally. Read relevant memory on
subsequent tasks rather than treating its existence as retrieval.

Broad skill changes need realistic isolated behavioral evaluation. Grade artifacts
and actions, include abstention/uncertainty cases, retain failures and compare
matched repeated trials before claiming better efficiency. Avoid global skill
installation or external issue creation unless requested.

Final handoff names the observable result, task/run, actual verification scope,
red-green evidence and remaining limitations. Agent summaries alone are not proof.
