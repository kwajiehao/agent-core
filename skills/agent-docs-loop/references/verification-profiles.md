# Build a repository verification helper

Use this when existing project commands cannot demonstrate a required acceptance
condition. Build inside the task's authorized paths. Prefer the repository's
testing language and existing drivers; a project-local script should run without
an agent or an installed global skill.

Discover from source and existing docs:

- surface: the public library call, CLI, API, browser or desktop path;
- launch: exact build/start command, dependencies and readiness signal;
- doctor: a read-only check of version, readiness, authentication and ownership;
- drive: real caller inputs, stable selectors or command/PTY/API interactions;
- observe: literal output, durable state, logs or action/result screenshots;
- isolation: unique ports, data directories and fixtures, or a documented limit;
- cleanup: resources this run owns and how evidence survives teardown.

Construct the smallest useful driver. Avoid internal setters that bypass the
promised path, broad mocks, swallowed exceptions and compile-only success.
Use real owned effects or a clearly scoped boundary substitute with an integration
check for what it cannot establish. For a local library test, launch and cleanup
may simply mean fixtures in a temporary directory.

Account for incidental command writes before preparation: bytecode caches, build
outputs, updated snapshots and logs. Redirect generated outputs to owned run or
approved ignored locations, or disable incidental writes. For example, use
`PYTHONDONTWRITEBYTECODE=1` for Python checks when the project does not ignore
bytecode. Preserve pre-existing outputs. Do not widen source-scope exemptions
merely to hide verifier-created changes.

Prove the helper end to end against the real repository: readiness, drive,
observation, cleanup and retained evidence. Where possible, challenge it with a
known failing revision or a defect seeded only in an isolated copy. Show the
failure before the correction and the passing condition afterward. A helper that
was never executed remains a draft. Capture setup failures as failures, not skips
that produce a green result.

Keep the exact command and observed condition in task acceptance. Optional
evidence paths can reference retained screenshots/logs; commands must still assert
the meaningful result and exit nonzero on failure. Copy verification instructions
to a concise repo-local skill or document only when future agents need them.

For repeated use, maintain a small feature index mapping each acceptance-relevant
entry point to its drive and observed result. Refresh affected entries after code
changes. Never claim one convenient path covers every mapped feature. Check the
helper and feature index together before using old evidence on a new revision.
