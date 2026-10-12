---
name: agent-docs-loop
description: Implement or resume a coding task with Agent Core's task contracts, durable handoffs and verification runner. Use for agent-docs task files or an explicit loop request with a repository. Do not turn repository assessment, explanation or review-only requests into implementation.
---

# Agent-Docs Loop

Own the requested outcome. The runner prepares durable context and verifies
declared behavior; the coordinator chooses the implementation and invokes any
required independent reviewer. Preserve the user's existing authorization.

## Resolve the request

Use the known Agent Core checkout as <agent-core> and the target repository as
<target-repo>. Installed copies record the checkout path in
references/installation.json; the Claude adapter records it as well. Otherwise
use a known checkout or discover it from the skill symlink/repository; ask for the
path only when it cannot be found. Run from any directory using:

    uv --project <agent-core> run python <agent-core>/loop/run_task.py --repo-root <target-repo> --resume

If uv is unavailable, use an existing Python environment with the dependencies
declared in Agent Core's pyproject.toml. Do not silently switch to a Python that
cannot import the runner. Provision a project environment within the authorized
setup scope, or report the concrete environment failure.

Explicit new work takes precedence over an unrelated unfinished task. Resume
discovery recovers context; it does not authorize implementing an old task when
the user asked for a different change. For a repository-only loop invocation,
follow the returned action:

- resume: read task, prompt, handoff and available verification. Continue in the
  existing run after checking evidence freshness. Preserve incomplete evidence.
- completed_context: recover the completed context. Handle a supplied new
  request; otherwise report the recovered state and ask what to build.
- intake_required: discover repository context and draft the requested task.
- Surface warnings. Never follow paths from skipped records or call stale
  verification current. Legacy runs remain context; create a new v2 run after
  restoring and reviewing their task contract.

## Intake an authorized change

Inspect repository instructions, relevant callers and tests, CI commands, local
changes, reusable repo memory and verification helpers. Infer allowed paths and
the coordination mode. Use solo for narrow work with clear evidence, review when
independent judgment adds value, and delegated when a separate maker is useful.
Describe the choice; do not ask the human to operate the workflow.

Create the task directly when the user supplied a clear, authorized change.
Confirmation is required only for missing product meaning, a material expansion
of scope or actions that need additional authority. A user's approval of a
previous recommendation is sufficient. Continue independent work while a
specific semantic question is pending.

For each acceptance condition, name an observable result and map it to a declared
test or smoke command. Derive commands from repository evidence. If there is no
credible verifier, build a small project-native helper inside the authorized
paths and prove it detects the failure; read
[verification-profiles.md](references/verification-profiles.md). Do not substitute
a compile check for behavior or ask the user to discover facts the agent can find.

Create a task using the runner's --new-task, --title, --allowed-path,
--test-command and --coordination-mode options. Pair each --acceptance-condition
with --acceptance-command. Supply task-specific --maker-characterization and/or
--reviewer-characterization when their mode requires them. Add --read-first and
--smoke-command only when relevant.

Read the generated task, replace Task/Acceptance placeholders, and retain the
user's constraints and important decisions there. Re-read that frozen contract
before implementation; a simulated context reset must not discard user steering.
When the contract changes, preserve the old run and prepare a new one.

## Execute and prove

1. Prepare with the task path and --prepare-run. Read prompt.md, the task,
   read_first files and the consuming repository's instructions. Read Agent
   Core's CODING.md and TESTING.md for implementation/testing choices.
2. Select the relevant evidence procedure from
   [playbooks.md](references/playbooks.md). Work in small verifiable units.
   Use a failing reproducer or regression before a fix where practical.
3. Implement directly or invoke the required maker. Give delegates file pointers,
   bounded ownership, the task contract and success criteria. Keep shared writes
   under one owner. Inspect their actual diffs and evidence.
4. Simplify after implementation. Remove speculative abstractions, dead code and
   symptom-only patches. Use an existing simplifier when useful and available;
   a direct coordinator pass is sufficient. No particular CLI/model is required.
5. For review/delegated mode, invoke an independent reviewer of the current full
   task delta, tests, behavior evidence and risks. Store findings in
   subagents/reviewer.md with an exact Verdict: approve line only when satisfied.
   Seal that review using the task path, --record-review and --run-dir. The seal
   binds the artifact to the code and task; it does not prove independence.
6. Run the task path with --verify-only --run-dir <run-dir>. The runner owns final
   execution of declared tests and optional smoke. Earlier focused development
   checks are useful; avoid an unconditional duplicate full-suite run.
   Plan incidental verifier writes such as bytecode/build caches into owned or
   approved output locations; see [verification profiles](references/verification-profiles.md).
7. Inspect verification.json and the command/artifact results. A pass covers only
   the mapped acceptance conditions. Do not declare completion if the requested
   outcome has an uncovered condition, stale evidence or an unresolved required
   decision. Fix the cause and re-review after changes invalidate the seal.

Keep handoff.md current with completed/pending work, hypotheses, commands and
owned resources. Before resuming a service, inspect its actual live handle rather
than treating a stale PID or status file as proof it runs. Never overlap drivers
of a shared instance. A command timeout is incomplete execution, not a product
diagnosis.

For autonomous work, state a checkable exit condition and scope/budget, checkpoint
each meaningful iteration, and change hypotheses when evidence refutes them.
Do not weaken the exit condition to make a run pass. External writes and
operational expansion retain their normal authorization requirements.

## Learn and hand off

Record consequential failures and human corrections even when a run fails.
Persist reusable lessons after their validity is established: prefer a type,
lint, test, canonical helper or runtime check; use brief repo memory only when
judgment cannot be encoded structurally. Add the regression to the behavior
evaluation suite before promoting a broad skill change. Do not edit installed
global skills or create external issues by inference.

Report the observable result, task/run paths, actual verification scope, red-green
evidence when applicable, and remaining gaps. Reviewer summaries are judgment;
runner records and actual artifacts are the evidence.
