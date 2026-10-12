# Task-specific evidence

Choose the procedure that matches the requested outcome. These are evidence
requirements, not mandatory extra agents or ceremony. Scale them to the change.

## Bug fix

Reproduce the observed failure at its real seam before editing. When cheap, capture
the behavior to a failing regression first. Trace the responsible ownership/data
flow and eliminate competing hypotheses with runtime evidence. Verify the same
trigger after the fix and preserve nearby valid behavior. If two attempts based
on one premise fail the same gate, reconsider that premise before adding guards.
A symptom disappearing after instrumentation is not a reproduced correction.

Map acceptance to the reproducer, relevant regressions and, when necessary, the
actual UI/CLI/API or durable state. Preserve useful failure output. Label a
non-reproducible report unverified and identify the missing observation.

## Feature

Name the user/caller behavior and the owning data shape before implementation.
Follow existing domain models and boundaries. For uncertain ownership, concurrency
or a consequential interface choice, compare plausible shapes using caller usage
and a small runnable sketch. Routine changes can proceed with the existing shape.
Choose an independent reviewer where uncertainty/risk justifies it; an architecture
bakeoff is optional, not a tax on every function boundary.

Prove the main path plus consequential rejection/recovery behavior through actual
public interfaces. If persistence or external effects are part of the promise,
observe those effects independently of the function that writes them.

## Refactor or migration

Record the behavior and callers being preserved before editing. Split the change
into units with independent checks and one owner for shared primitives. Migrate
callers and remove obsolete internal APIs together when authorized; retain public
compatibility required by the product. Verify all affected consumers. Compare
outputs at the original and changed revisions when ordinary tests leave a gap.
Avoid compatibility scaffolding whose only purpose is the task's phase boundary.

## Performance

Capture a reproducible baseline with a representative workload. Identify what the
measurement includes, environment identities, warmup, caching and noisy factors.
Change one grounded hypothesis and repeat matched measurements. Report samples
and variation, not only the best run. Verify correctness alongside speed.
An optimization is accepted when the declared metric improves within the stated
conditions and behavior remains correct. Record discarded experiments separately.

## Investigation or review

Keep the deliverable read-only unless changes were separately requested. Cite
source/runtime observations and label inferred causes. Use controlled diagnostics
to resolve observable questions; ask the human only about meaning or unavailable
information. Do not create an implementation task merely because a repository
path or bug appears in the request.

## Autonomous or interrupted work

State the exit predicate, scope, budget and owned resources. Advance in verifiable
units and keep a decision/command trail. On pickup, recover handoff and artifacts,
then validate freshness and actual resource handles. Reuse still-current evidence;
rerun only what is invalidated or missing. A stopped job is not a completed job.

When a hypothesis fails, preserve the evidence and pivot. Stop at a genuine need
for new authority or product meaning and retain a precise next action. Do not
broaden the task or weaken acceptance because progress is difficult.
