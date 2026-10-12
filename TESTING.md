# Testing Conventions

Repo-specific setup, local services, credentials, fixtures, and sample assets
belong in the consuming repo's docs. This file holds the testing conventions
that are useful across repos.

## Regression Tests

Regression tests should reproduce the observed failure as directly as possible.
Run a new regression before implementation when practical and retain the actual
failure output. Then verify the correction and relevant existing behavior. A
test that also passes the defective implementation does not establish the fix.

Prefer:

- existing repo fixtures/assets
- the same helper/function path used by production
- assertions on the specific bad output that caused the bug
- the narrowest command that exercises the changed behavior

Avoid:

- generated test data when a committed fixture can reproduce the issue
- broad mocks that skip the failing subsystem
- asserting implementation details unless the behavior cannot be observed otherwise
- widening a test command to an expensive suite when a focused command would
  verify the task

## Smoke Tests

Smoke coverage is optional in the simplified runner. Add `smoke_command` to a
task when unit/regression tests are not enough to prove the user-facing or
integration behavior.

Good smoke commands:

- run against realistic local setup or a documented dev endpoint
- cover the main happy path and at least one important unhappy path when cheap
- exit non-zero on failure
- allow callers to override fixture paths and ports through environment vars
- avoid hardcoded secrets

Keep smoke setup in the command itself or in repo-owned scripts such as
`scripts/smoke-*.sh`. The runner only executes the command and records the
result.

## Acceptance Evidence

Map every required observable condition to a declared test or smoke command in
task frontmatter. Assert literal user/caller results, including durable effects
when promised. The runner executes the final commands; earlier focused checks
are developmental evidence rather than a reason to repeat a full suite twice.

Review approval and passing command records apply to their recorded task and
code snapshot. Re-review when that snapshot changes. A schema-valid artifact,
compilation, a filename, or a model's summary is not proof of behavior.

## Workflow Evaluations

Exercise skills with organic requests in isolated repositories and hold expected
outcomes away from the acting agent. Inspect actual artifacts and actions. Include
cases where a skill should abstain, reuse current evidence or report uncertainty.
Record both failures and successes; distinguish tooling unit tests from real
agent trials. Compare repeated matched trials before making performance claims.
The shared evaluation runner lives in the sibling agent-skills repository's
evals directory; it is optional development tooling, not a production dependency.

## Fixtures And Sample Assets

When a smoke or regression test needs a real asset such as media, a payload, or
a database fixture, default to one already committed to the repo. Let callers
override the path with an environment variable when practical.

Do not commit copyrighted material solely to satisfy tests.

## Secrets

Ask the user for API keys. Never hardcode, commit, or persist them in run
artifacts or task docs.
