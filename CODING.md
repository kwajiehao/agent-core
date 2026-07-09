# Coding Principles

## Implementation shape

Start with the smallest change that fixes the observed behavior.

## Simplicity criterion

All else being equal, simpler is better. A change that technically satisfies an
acceptance criterion but adds awkward control flow, speculative abstractions, or
task-specific special cases should earn its complexity.

When deciding whether to keep a change, weigh the complexity cost against the
behavioral improvement:

- A narrow bug fix that adds one clear guard and a focused regression test is
  usually worth keeping.
- A fix that adds a new mode, flag, helper layer, or broad interface change just
  to satisfy one edge case is probably not worth it unless the edge case is
  central to the product behavior.
- Removing duplicated logic and preserving or improving test/smoke coverage is
  a simplification win.
- Replacing custom parsing, polling, or retry code with an existing repo helper
  while keeping behavior equivalent is a simplification win.
- A tiny acceptance improvement that requires fragile branching across several
  files is usually worse than a slightly narrower fix that keeps the contract
  obvious.
- A behavior-neutral change that deletes code, reduces special cases, or makes
  ownership clearer is worth keeping when tests and smoke coverage still pass.

Before adding helpers, flags, new return types, or changing function signatures, prefer:
1. Keep the existing public/internal contract unchanged.
2. Localize edge-case handling inside the function that already owns the behavior.
3. Add one focused regression test for the failing path.
4. Introduce a new abstraction only when the test or existing call sites make it necessary.

Do not change a function signature unless:
- an existing caller genuinely needs new information, or
- keeping the signature would create duplicated or misleading behavior, and
- the change is smaller than the alternatives.

When fixing edge cases, avoid speculative generality. Fix the known edge case
first, then broaden only when there is a second concrete case.

## Service reuse

Handlers call existing services and helpers. Do not duplicate business logic.

## No task boundaries in production code

Task docs reference other tasks for context, but production code must never
encode which task or PR implements what. Constants, error messages, and API
responses must describe the system as it is — not how the work was split. If a
task doc defines a constant that excludes cases "because they're in another
task," expand it to cover the full system concept and add a comment explaining
the domain reason instead.

## Types

All changes should be strictly typed as much as possible. All function
arguments and returns should be strictly typed.

## Repo-specific patterns

File placement, router wiring, model locations, and test file layout are
defined per repo — see the consuming repo's `agent-docs/` docs and `AGENTS.md`.
