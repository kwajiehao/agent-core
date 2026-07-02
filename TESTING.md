# Testing Conventions

Repo-specific setup (local stack, dev server, connection details, sample
fixtures) lives in the consuming repo's `agent-docs/TESTING.md`. This file
holds the conventions that are true everywhere.

## Regression tests

Regression tests should reproduce the observed failure as directly as possible.

Prefer:
- existing repo fixtures/assets
- the same helper/function path used by production
- assertions on the specific bad output that caused the bug

Avoid:
- generated test data when a committed fixture can reproduce the issue
- broad mocks that skip the failing subsystem
- asserting implementation details unless the behavior cannot be observed otherwise

## Smoke tests

Each task must have a smoke test script in
`agent-docs/smoke-tests/<task-file-stem>.sh`. Conventions:

- Takes the API key as `$1` when the repo's `loop.yaml` configures
  `api_key_env`; takes no arguments otherwise
- Uses a `check()` helper for pass/fail reporting
- Covers happy and unhappy flows
- Exits non-zero on failure
- Never hardcodes API keys or other secrets

Smoke tests run against the live local stack, not mocks. The runner brings up
the services declared in `agent-docs/loop.yaml` before executing the script
and tears down anything it started.

## Fixtures and sample assets

When a smoke test needs a real asset (media file, large payload), default to
one already committed to the repo — the repo's `agent-docs/TESTING.md` lists
the canonical ones. Smoke tests should let the caller override the path with
an env var (e.g. `SAMPLE_VIDEO=/path/to/file`) so contributors can supply
their own. Do not commit copyrighted material to satisfy these tests.

## Secrets

Ask the user for API keys. Never hardcode, commit, or persist them in run
artifacts or task docs.
