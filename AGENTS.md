# Agent Instructions

- Keep this file as a routing layer. Do not duplicate the full workflow here.
- Use [README.md](/Users/kwa/Documents/personal/agent-core/README.md) for the runner contract and role model.
- Use [WORKFLOW.md](/Users/kwa/Documents/personal/agent-core/WORKFLOW.md) for task execution, including `coordination.mode`, simplify, subagents, handoff, and final verification.
- Use [CODING.md](/Users/kwa/Documents/personal/agent-core/CODING.md) and [TESTING.md](/Users/kwa/Documents/personal/agent-core/TESTING.md) for agent behavior.
- The main agent is the coordinator. The runner never invokes or manages agents.
- Do not treat agent summaries or reviewer approval as final verification. Use runner artifacts as the source of truth.
- Run tests with `uv run pytest`.
