# Repo-Local Agent Skills

Optional reusable skills can live here:

```text
agent-docs/skills/<skill-name>/SKILL.md
```

The simplified runner does not auto-discover skills. Reference a skill from
`AGENTS.md`, a task body, or `read_first` when an agent should load it.

Create or update a skill only after a passed run reveals reusable workflow or
repo knowledge.

When a skill implies subagent work, the parent agent should still keep the
subagent brief and findings in the current run's `subagents/` directory.
