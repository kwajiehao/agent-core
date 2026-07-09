# TODO

## Feature Gaps

### Enforce attempt budgets in coordinator state

**Status:** Not started

`max_attempts`, `max_no_progress_attempts`, and token budgets are currently config-only. Add coordinator state-machine enforcement so unattended runs can stop or advance deterministically.

Target run status transitions:

- `prepared`
- `maker_done`
- `verification_failed`
- `needs_verifier`
- `accepted`
- `blocked`

Implementation notes:

- Track attempt counts per run.
- Enforce max total attempts.
- Enforce max no-progress attempts.
- Enforce token budgets where coordinator decisions are made.
- Persist status transitions so interrupted runs can resume consistently.

### Prevent background service startup races

**Status:** Not started

Background services currently start and smoke tests run immediately unless `health_url` is present. This can race when `background: true` services need startup time.

Reference: `loop/runner.py:864`

Implementation options:

- Require `health_url` whenever `background: true`.
- Or add explicit `startup_delay_seconds`.

Preferred behavior should fail fast with a clear config error when a background service has no readiness strategy.

### Stop passing secrets as argv

**Status:** Not started

The runner hides the API key from artifacts, but still passes it as `$1` to smoke scripts. That can expose the secret in process listings while the script runs.

Reference: `loop/runner.py:814`

Implementation direction:

- Pass the key through `SMOKE_API_KEY` in the environment.
- Keep `$1` as a backwards-compatible option for existing smoke scripts.
- Update docs/templates to prefer `SMOKE_API_KEY`.
- Ensure artifacts and logs continue to redact the secret.
