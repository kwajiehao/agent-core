# Agent Instructions

- Keep this file as a routing layer. Do not duplicate the full workflow here.
- Use [README.md](README.md) for the runner contract and role model.
- Use [WORKFLOW.md](WORKFLOW.md) for task execution, including `coordination.mode`, simplify, subagents, handoff, and final verification.
- Use [CODING.md](CODING.md) and [TESTING.md](TESTING.md) for agent behavior.
- The main agent is the coordinator. The runner never invokes or manages agents.
- Do not treat agent summaries or reviewer approval as final verification. Use runner artifacts as the source of truth.
- Run tests with `uv run pytest`, or `python -m pytest` from an environment containing the declared dependencies.
