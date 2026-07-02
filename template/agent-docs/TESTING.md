# Testing Guide (repo-specific)

General conventions live in agent-core's `TESTING.md`. This file holds what is
specific to this repo. Fill in every section; delete the ones that do not apply.

## Local stack

<!-- How to bring up databases, queues, emulators. First-time setup vs. daily
     use. These commands should match the services in loop.yaml. -->

## Local server

<!-- The exact command to run the dev server, required env vars, how long
     startup takes, and the URL to poll for readiness. -->

## API key

<!-- Which env var smoke scripts receive as $1 (must match loop.yaml
     api_key_env), and how the user obtains a key. Never hardcode or commit. -->

## Sample fixtures

<!-- Canonical committed assets for smoke tests: path, size, what each is for.
     Name the env var callers can use to override the asset path. -->
