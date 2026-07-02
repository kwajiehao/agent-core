# Repo-Local Agent Skills

Store skills specific to this repo's task execution here:

```text
agent-docs/skills/<skill-name>/SKILL.md
```

The loop runner discovers these skills by reading their `SKILL.md` frontmatter
and injects keyword-matched skill paths into maker and verifier prompts. A
repo-local skill with the same name as an agent-core role skill overrides it.

Skills created from reflection should only be written after an accepted run,
and only when the run captured repeated or hard workflow knowledge. Promote a
skill into agent-core's `skills/` when it is useful across repos.
