# Agent Core

A repository-independent task runner for coding agents. It prepares durable
context and verifies declared behavior, scope, evidence freshness and command
outcomes. The coordinator chooses designs, invokes agents and owns completion.

## Use

Install the agent-facing skill from this checkout:

    python scripts/install_skills.py

The default Codex discovery location is ~/.agents/skills. An explicit CODEX_HOME
or --codex-dest overrides it. Claude receives a skill copy and a slash-command
adapter naming this checkout. Existing entries are preserved unless --force is
requested; replacing a symlink never deletes its target.

Ask your coding agent:

    Use agent-docs-loop for /path/to/repository. Fix <specific behavior>.

A clear authorized request starts discovery and task creation without a routine
confirmation gate. A repository-only invocation recovers prior context. Explicit
new work takes precedence over unrelated unfinished tasks. Assessment and
explanation requests stay read-only.

Read [WORKFLOW.md](WORKFLOW.md) for execution and
[the skill](skills/agent-docs-loop/SKILL.md) for the detailed agent procedure.
[CODING.md](CODING.md) and [TESTING.md](TESTING.md) hold cross-repository conventions.

## Environment

Command execution is supported on POSIX (macOS/Linux). Use uv from this checkout,
or an existing Python 3.11+ environment containing the
dependencies in pyproject.toml. Tests additionally require the dev dependencies.

    uv run pytest
    # Equivalent in a provisioned environment:
    python -m pytest

From another directory:

    uv --project /path/to/agent-core run python /path/to/agent-core/loop/run_task.py --repo-root /path/to/repository --resume

The runner does not provision services, infer verification commands or launch
agents. Repository setup belongs in project-owned commands.

## Task contract

A task is Markdown with YAML frontmatter:

    ---
    id: search-pagination
    title: Preserve next-page results
    read_first:
      - README.md
    allowed_paths:
      - src/search/**
      - tests/search/**
    test_commands:
      - python -m pytest tests/search/test_pagination.py
    acceptance:
      - condition: A second page returns the remaining items without duplicates.
        command: python -m pytest tests/search/test_pagination.py
    coordination:
      mode: review
      reviewer:
        characterization: Search reviewer focused on pagination and regression evidence.
    ---

Required fields are id, title, allowed_paths, nonempty test_commands and
acceptance mappings for v2 execution. Each acceptance command must be one of the
declared test commands or the optional smoke_command. A mapping may additionally
name an evidence file produced by its command; verification retains its identity.
Conditions describe observable behavior. Mapping an unrelated green command does
not establish that behavior; task author/reviewer judgment remains necessary.

coordination defaults to solo. review requires reviewer characterization and an
approved, sealed subagents/reviewer.md. delegated additionally requires maker
characterization and subagents/maker.md. Sealing records freshness, not proof of
independent agent execution.

## CLI

Relative task and run paths resolve against `--repo-root`, not the caller's
working directory. Absolute paths remain supported.

Create a task, then replace its Task and Acceptance placeholders before preparation:

    python loop/run_task.py --repo-root /path/to/repository --new-task search-pagination --title 'Preserve next-page results' --allowed-path 'src/search/**' --allowed-path 'tests/search/**' --test-command 'python -m pytest tests/search/test_pagination.py' --acceptance-condition 'Next page returns remaining items without duplicates.' --acceptance-command 'python -m pytest tests/search/test_pagination.py' --coordination-mode review --reviewer-characterization 'Independent search-platform reviewer'

Prepare a run:

    python loop/run_task.py agent-docs/tasks/search-pagination-preserve-next-page-results.md --repo-root /path/to/repository --prepare-run

After implementation and independent review, seal the reviewer artifact:

    python loop/run_task.py <task> --repo-root <repo> --record-review --run-dir <run>

Finally verify:

    python loop/run_task.py <task> --repo-root <repo> --verify-only --run-dir <run>

Resume discovery:

    python loop/run_task.py --repo-root <repo> --resume

The verification command executes all declared tests and optional smoke and writes
structured outcomes. Command deadlines terminate owned descendants; retained
output is bounded to 64 KiB per stdout/stderr and truncation is reported.
Evidence paths should live under
the run's own directory or a documented ignored output location so generation
does not change the source snapshot.

## Evidence and limitations

Prepared v2 runs bind a task snapshot, initial HEAD and repository file states.
Scope verification covers tracked and nonignored untracked files, including
commits, additions/deletions, changes to initially dirty files and edits made by
test/smoke commands. Ignored untracked outputs are not source-scope evidence.
Git inspection failure is a
failed verification condition. The check is a post-action scope gate, not a sandbox.

Review and passing verification describe their exact task, code and artifacts.
Subsequent changes invalidate affected evidence. Missing, malformed, stale or
interrupted records cannot establish completion. Resume validates recorded
structure and freshness; historical passes are not current proof.

Legacy runs are retained as context and reported with warnings. They lack a
trustworthy v2 content baseline; explicitly restore/review their task contract and
prepare a new run before v2 verification. A new baseline proves its own subsequent
delta, not work that occurred before it.
A new prepared run supersedes older attempts for the same task in discovery;
their artifacts remain intact. Other unfinished tasks retain their precedence.

The runner proves mapped declared checks, not exhaustive product correctness or
reviewer independence. The coordinator must ensure acceptance covers the user's
full request and that the commands observe the intended behavior.

## Durable context

Tasks, repo memory and local skill indexes live under agent-docs. Each run has
prompt.md, task.snapshot.md, run.json, handoff.md and subagents/, plus review and
verification artifacts as work advances. Generated runs are ignored by Git;
task contracts and reusable knowledge can be versioned.

Capture important failed attempts and corrections, then encode validated lessons
as tests, types, lint or helpers wherever practical. For behavioral workflow
evaluations, see the sibling agent-skills repository's evals tooling.
