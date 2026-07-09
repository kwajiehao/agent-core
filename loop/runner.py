# ABOUTME: Implements a small task runner for agent-docs tasks.
# ABOUTME: Verifies changed-file scope plus task-owned test and smoke commands.

from __future__ import annotations

import argparse
import dataclasses
import fnmatch
import json
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

CoordinationMode = Literal["solo", "review", "delegated"]


class RunnerError(RuntimeError):
    """Base exception for local loop runner failures."""


class FrontmatterError(RunnerError):
    """Raised when task frontmatter is invalid."""


@dataclass(frozen=True)
class CoordinationSpec:
    mode: CoordinationMode = "solo"
    maker_characterization: str | None = None
    reviewer_characterization: str | None = None

    def to_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class TaskSpec:
    path: Path
    repo_root: Path
    id: str
    title: str
    allowed_paths: list[str]
    read_first: list[str]
    test_commands: list[str]
    smoke_command: str | None = None
    coordination: CoordinationSpec = field(default_factory=CoordinationSpec)


@dataclass(frozen=True)
class CommandResult:
    command: str
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False

    def to_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class RunContext:
    task: TaskSpec
    run_id: str
    run_dir: Path


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    details: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class VerificationResult:
    status: str
    gates: list[GateResult]
    commands: list[CommandResult]

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "gates": [gate.to_json() for gate in self.gates],
            "commands": [command.to_json() for command in self.commands],
        }


def load_task(task_path: str | Path, repo_root: str | Path) -> TaskSpec:
    task_file = Path(task_path).resolve()
    root = Path(repo_root).resolve()
    frontmatter, _ = _read_frontmatter(task_file)

    required = ["id", "title", "allowed_paths", "test_commands"]
    missing = [key for key in required if key not in frontmatter]
    if missing:
        raise FrontmatterError(f"{task_file} missing required frontmatter: {', '.join(missing)}")

    smoke_command = frontmatter.get("smoke_command")
    return TaskSpec(
        path=task_file,
        repo_root=root,
        id=str(frontmatter["id"]),
        title=str(frontmatter["title"]),
        allowed_paths=_string_list(frontmatter["allowed_paths"], "allowed_paths"),
        read_first=_string_list(frontmatter.get("read_first", []), "read_first"),
        test_commands=_string_list(frontmatter["test_commands"], "test_commands"),
        smoke_command=str(smoke_command).strip() if smoke_command else None,
        coordination=_coordination_spec(frontmatter.get("coordination")),
    )


def check_allowed_paths(
    changed_files: list[str],
    allowed_paths: list[str],
    repo_root: str | Path,
) -> list[str]:
    root = Path(repo_root).resolve()
    violations: list[str] = []

    for changed in changed_files:
        changed_path = Path(changed)
        if changed_path.is_absolute():
            absolute_changed = changed_path.resolve()
            try:
                relative_changed = absolute_changed.relative_to(root).as_posix()
            except ValueError:
                relative_changed = absolute_changed.as_posix()
        else:
            relative_changed = changed.replace("\\", "/")
            absolute_changed = (root / relative_changed).resolve()

        if not _path_allowed(relative_changed, absolute_changed.as_posix(), allowed_paths, root):
            violations.append(changed)

    return violations


def run_command(command: str, cwd: str | Path, timeout_seconds: int = 1_800) -> CommandResult:
    return _run_subprocess(command, cwd, label=command, timeout_seconds=timeout_seconds)


def create_task(
    repo_root: str | Path,
    *,
    task_id: str,
    title: str,
    read_first: list[str],
    allowed_paths: list[str],
    test_commands: list[str],
    coordination_mode: CoordinationMode = "solo",
    maker_characterization: str | None = None,
    reviewer_characterization: str | None = None,
    smoke_command: str | None = None,
    overwrite: bool = False,
) -> Path:
    root = Path(repo_root).resolve()
    clean_task_id = task_id.strip()
    clean_title = title.strip()
    if not clean_task_id:
        raise FrontmatterError("task id is required")
    if not clean_title:
        raise FrontmatterError("task title is required")
    if not allowed_paths:
        raise FrontmatterError("--allowed-path is required when creating a task")
    if not test_commands:
        raise FrontmatterError("--test-command is required when creating a task")

    coordination = _coordination_spec(
        {
            "mode": coordination_mode,
            "maker": _role_config(maker_characterization),
            "reviewer": _role_config(reviewer_characterization),
        }
    )
    task_dir = root / "agent-docs" / "tasks"
    task_dir.mkdir(parents=True, exist_ok=True)
    _bootstrap_agent_docs(root)

    filename = (
        f"{_filename_part(clean_task_id, 'task')}-"
        f"{_filename_part(clean_title, 'work', lowercase=True)}.md"
    )
    task_path = task_dir / filename
    if task_path.exists() and not overwrite:
        raise RunnerError(f"{task_path} already exists; use --force to overwrite it")

    task_path.write_text(
        _task_template(
            task_id=clean_task_id,
            title=clean_title,
            read_first=read_first,
            allowed_paths=allowed_paths,
            test_commands=test_commands,
            coordination=coordination,
            smoke_command=smoke_command.strip() if smoke_command else None,
        ),
        encoding="utf-8",
    )
    return task_path


def prepare_run(task: TaskSpec, repo_root: str | Path) -> RunContext:
    root = Path(repo_root).resolve()
    run_id = _new_run_id()
    run_dir = root / "agent-docs" / "runs" / task.id / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    subagents_dir = run_dir / "subagents"
    subagents_dir.mkdir()

    context = RunContext(task=task, run_id=run_id, run_dir=run_dir)
    (run_dir / "prompt.md").write_text(_prompt(context), encoding="utf-8")
    (run_dir / "handoff.md").write_text(_handoff_template(context), encoding="utf-8")
    (subagents_dir / "README.md").write_text(_subagents_readme(context), encoding="utf-8")
    _write_run_json(
        context,
        {
            "status": "prepared",
            "baseline_changed_files": collect_changed_files(root),
            "handoff": str(run_dir / "handoff.md"),
            "subagents_dir": str(subagents_dir),
            "coordination": task.coordination.to_json(),
            "verification": {
                "test_commands": task.test_commands,
                "smoke_command": task.smoke_command,
            },
        },
    )
    return context


def verify_task(
    task: TaskSpec,
    repo_root: str | Path,
    run_dir: str | Path,
    *,
    command_timeout_seconds: int = 1_800,
) -> VerificationResult:
    root = Path(repo_root).resolve()
    output_dir = Path(run_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    gates: list[GateResult] = []
    commands: list[CommandResult] = []

    changed_files = [
        path
        for path in filter_baseline_changed_files(
            collect_changed_files(root),
            _load_baseline_changed_files(output_dir),
        )
        if not path.startswith("agent-docs/runs/")
    ]
    violations = check_allowed_paths(changed_files, task.allowed_paths, root)
    gates.append(
        GateResult(
            name="diff_scope",
            passed=not violations,
            details={"changed_files": changed_files, "violations": violations},
        )
    )

    coordination_gate = _coordination_gate(task, output_dir)
    gates.append(coordination_gate)
    _write_json(output_dir / "coordination.json", coordination_gate.to_json())

    test_results: list[CommandResult] = []
    for command in task.test_commands:
        result = run_command(command, root, timeout_seconds=command_timeout_seconds)
        test_results.append(result)
        commands.append(result)
    _write_json(output_dir / "tests.json", [result.to_json() for result in test_results])

    test_count = len(test_results)
    tests_passed = test_count > 0 and all(result.exit_code == 0 for result in test_results)
    test_details: dict[str, Any] = {"count": test_count}
    if test_count == 0:
        test_details["error"] = "test_commands must contain at least one command"
    gates.append(GateResult(name="tests", passed=tests_passed, details=test_details))

    smoke_result: CommandResult | None = None
    if task.smoke_command:
        smoke_result = run_command(
            task.smoke_command,
            root,
            timeout_seconds=command_timeout_seconds,
        )
        commands.append(smoke_result)
        smoke_passed = smoke_result.exit_code == 0
        smoke_details = {
            "command": smoke_result.command,
            "exit_code": smoke_result.exit_code,
        }
    else:
        smoke_passed = True
        smoke_details = {"skipped": True, "reason": "no smoke_command configured"}
    gates.append(GateResult(name="smoke", passed=smoke_passed, details=smoke_details))
    _write_json(output_dir / "smoke.json", smoke_result.to_json() if smoke_result else None)

    status = "passed" if all(gate.passed for gate in gates) else "failed"
    result = VerificationResult(status=status, gates=gates, commands=commands)
    _write_json(output_dir / "verification.json", result.to_json())
    return result


def collect_changed_files(repo_root: str | Path) -> list[str]:
    root = Path(repo_root).resolve()
    tracked = _git_lines(root, ["git", "diff", "--name-only"])
    staged = _git_lines(root, ["git", "diff", "--cached", "--name-only"])
    untracked = _git_lines(root, ["git", "ls-files", "--others", "--exclude-standard"])
    return sorted(set(tracked + staged + untracked))


def filter_baseline_changed_files(current: list[str], baseline: list[str]) -> list[str]:
    baseline_set = set(baseline)
    return [path for path in current if path not in baseline_set]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create, prepare, or verify an agent-docs task run."
    )
    parser.add_argument("task", nargs="?", help="Path to agent-docs/tasks/<task>.md")
    parser.add_argument("--repo-root", default=".", help="Repository root; defaults to cwd")
    parser.add_argument("--new-task", help="Create agent-docs/tasks/<id>-<title>.md")
    parser.add_argument("--title", help="Task title for --new-task")
    parser.add_argument(
        "--read-first",
        action="append",
        default=[],
        help="Context file to read first",
    )
    parser.add_argument(
        "--allowed-path",
        action="append",
        default=[],
        help="Allowed changed-file glob",
    )
    parser.add_argument(
        "--test-command",
        action="append",
        default=[],
        help="Required verification command",
    )
    parser.add_argument(
        "--coordination-mode",
        choices=["solo", "review", "delegated"],
        default="solo",
        help="Subagent artifact policy for --new-task",
    )
    parser.add_argument(
        "--maker-characterization",
        help="Maker role characterization for --new-task",
    )
    parser.add_argument(
        "--reviewer-characterization",
        help="Reviewer role characterization for --new-task",
    )
    parser.add_argument("--smoke-command", help="Optional smoke command for --new-task")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing generated task")
    parser.add_argument("--prepare-run", action="store_true", help="Generate prompt/run artifacts")
    parser.add_argument("--verify-only", action="store_true", help="Run verification gates")
    parser.add_argument("--run-dir", help="Existing run artifact directory for --verify-only")
    parser.add_argument("--timeout-seconds", type=int, default=1_800, help="Per-command timeout")
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve()
    try:
        if args.new_task:
            if args.task:
                parser.error("task path cannot be provided with --new-task")
            if not args.title:
                parser.error("--title is required with --new-task")
            task_path = create_task(
                root,
                task_id=args.new_task,
                title=args.title,
                read_first=args.read_first,
                allowed_paths=args.allowed_path,
                test_commands=args.test_command,
                coordination_mode=_coordination_mode(args.coordination_mode),
                maker_characterization=args.maker_characterization,
                reviewer_characterization=args.reviewer_characterization,
                smoke_command=args.smoke_command,
                overwrite=args.force,
            )
            print(f"task={task_path}")
            return 0

        if not args.task:
            parser.error("task path is required unless --new-task is used")
        task = load_task(args.task, root)

        if args.verify_only:
            run_dir = (
                Path(args.run_dir).resolve()
                if args.run_dir
                else root / "agent-docs" / "runs" / task.id / _new_run_id()
            )
            result = verify_task(
                task,
                root,
                run_dir,
                command_timeout_seconds=args.timeout_seconds,
            )
            print(json.dumps(result.to_json(), indent=2))
            return 0 if result.status == "passed" else 1

        context = prepare_run(task, root)
        print(f"run_dir={context.run_dir}")
        print(f"prompt={context.run_dir / 'prompt.md'}")
        return 0
    except RunnerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def _read_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise FrontmatterError(f"{path} does not start with YAML frontmatter")
    parts = text.split("---\n", 2)
    if len(parts) != 3:
        raise FrontmatterError(f"{path} has an unterminated YAML frontmatter block")
    raw = yaml.safe_load(parts[1]) or {}
    if not isinstance(raw, dict):
        raise FrontmatterError(f"{path} frontmatter must be a mapping")
    return raw, parts[2]


def _string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise FrontmatterError(f"{field_name} must be a list, got {type(value).__name__}")
    return [str(item) for item in value]


def _role_config(characterization: str | None) -> dict[str, str] | None:
    if characterization is None:
        return None
    return {"characterization": characterization}


def _coordination_spec(value: Any) -> CoordinationSpec:
    if value is None:
        return CoordinationSpec()
    if not isinstance(value, dict):
        raise FrontmatterError(
            f"coordination must be a mapping, got {type(value).__name__}"
        )

    raw_mode = value.get("mode", "solo")
    if not isinstance(raw_mode, str):
        raise FrontmatterError(
            f"coordination.mode must be a string, got {type(raw_mode).__name__}"
        )
    raw_mode = raw_mode.strip()
    mode = _coordination_mode(raw_mode)
    maker_characterization = _role_characterization(value, "maker")
    reviewer_characterization = _role_characterization(value, "reviewer")

    if mode == "review" and not reviewer_characterization:
        raise FrontmatterError(
            "coordination.reviewer.characterization is required when "
            "coordination.mode is review"
        )
    if mode == "delegated":
        missing: list[str] = []
        if not maker_characterization:
            missing.append("coordination.maker.characterization")
        if not reviewer_characterization:
            missing.append("coordination.reviewer.characterization")
        if missing:
            raise FrontmatterError(
                f"{', '.join(missing)} required when coordination.mode is delegated"
            )

    return CoordinationSpec(
        mode=mode,
        maker_characterization=maker_characterization,
        reviewer_characterization=reviewer_characterization,
    )


def _coordination_mode(value: str) -> CoordinationMode:
    if value == "solo":
        return "solo"
    if value == "review":
        return "review"
    if value == "delegated":
        return "delegated"
    raise FrontmatterError(
        "coordination.mode must be one of: solo, review, delegated"
    )


def _role_characterization(coordination: dict[str, Any], role: str) -> str | None:
    role_config = coordination.get(role)
    if role_config is None:
        return None
    if not isinstance(role_config, dict):
        raise FrontmatterError(
            f"coordination.{role} must be a mapping, got {type(role_config).__name__}"
        )
    value = role_config.get("characterization")
    if value is None:
        return None
    if not isinstance(value, str):
        raise FrontmatterError(
            f"coordination.{role}.characterization must be a string, "
            f"got {type(value).__name__}"
        )
    characterization = str(value).strip()
    return characterization or None


def _coordination_gate(task: TaskSpec, output_dir: Path) -> GateResult:
    required_artifacts = _required_subagent_artifacts(task.coordination.mode)
    subagents_dir = output_dir / "subagents"
    missing_artifacts: list[str] = []
    empty_artifacts: list[str] = []
    invalid_artifacts: list[str] = []
    invalid_artifact_errors: dict[str, str] = {}
    artifact_texts: dict[str, str] = {}

    for artifact in required_artifacts:
        path = subagents_dir / artifact
        artifact_label = f"subagents/{artifact}"
        if not path.exists():
            missing_artifacts.append(artifact_label)
            continue
        if not path.is_file():
            invalid_artifacts.append(artifact_label)
            invalid_artifact_errors[artifact_label] = "not a file"
            continue
        try:
            artifact_text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            invalid_artifacts.append(artifact_label)
            invalid_artifact_errors[artifact_label] = str(exc)
            continue
        if not artifact_text.strip():
            empty_artifacts.append(artifact_label)
            continue
        artifact_texts[artifact_label] = artifact_text

    reviewer_verdict: str | None = None
    reviewer_approved: bool | None = None
    reviewer_label = "subagents/reviewer.md"
    if "reviewer.md" in required_artifacts and reviewer_label in artifact_texts:
        reviewer_verdict = _reviewer_verdict(artifact_texts[reviewer_label])
        reviewer_approved = reviewer_verdict == "approve"

    details: dict[str, Any] = {
        "mode": task.coordination.mode,
        "required_artifacts": [f"subagents/{artifact}" for artifact in required_artifacts],
        "missing_artifacts": missing_artifacts,
        "empty_artifacts": empty_artifacts,
        "invalid_artifacts": invalid_artifacts,
    }
    if invalid_artifact_errors:
        details["invalid_artifact_errors"] = invalid_artifact_errors
    if reviewer_verdict is not None or "reviewer.md" in required_artifacts:
        details["reviewer_verdict"] = reviewer_verdict
        details["reviewer_approved"] = reviewer_approved

    passed = not missing_artifacts and not empty_artifacts and not invalid_artifacts
    if "reviewer.md" in required_artifacts:
        passed = passed and reviewer_approved is True
        if (
            reviewer_verdict is None
            and reviewer_label not in missing_artifacts
            and reviewer_label not in empty_artifacts
            and reviewer_label not in invalid_artifacts
        ):
            details["error"] = "subagents/reviewer.md must contain a 'Verdict: approve' line"
        elif reviewer_approved is False:
            details["error"] = "reviewer verdict must be approve"

    return GateResult(name="coordination", passed=passed, details=details)


def _required_subagent_artifacts(mode: CoordinationMode) -> list[str]:
    if mode == "solo":
        return []
    if mode == "review":
        return ["reviewer.md"]
    return ["maker.md", "reviewer.md"]


def _reviewer_verdict(text: str) -> str | None:
    verdict: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Verdict:"):
            verdict = stripped.split(":", 1)[1].strip() or None
    return verdict


def _bootstrap_agent_docs(repo_root: Path) -> None:
    agent_docs = repo_root / "agent-docs"
    (agent_docs / "tasks").mkdir(parents=True, exist_ok=True)
    (agent_docs / "skills").mkdir(parents=True, exist_ok=True)
    _write_text_if_missing(agent_docs / "MEMORY.md", _memory_template())
    _write_text_if_missing(agent_docs / "skills" / "README.md", _skills_readme_template())


def _write_text_if_missing(path: Path, text: str) -> None:
    if not path.exists():
        path.write_text(text, encoding="utf-8")


def _task_template(
    *,
    task_id: str,
    title: str,
    read_first: list[str],
    allowed_paths: list[str],
    test_commands: list[str],
    coordination: CoordinationSpec,
    smoke_command: str | None,
) -> str:
    lines = [
        "---",
        f"id: {_yaml_scalar(task_id)}",
        f"title: {_yaml_scalar(title)}",
    ]
    if read_first:
        lines.append("read_first:")
        lines.extend(_yaml_list(read_first))
    lines.append("allowed_paths:")
    lines.extend(_yaml_list(allowed_paths))
    lines.append("test_commands:")
    lines.extend(_yaml_list(test_commands))
    lines.append("coordination:")
    lines.append(f"  mode: {coordination.mode}")
    if coordination.maker_characterization:
        lines.append("  maker:")
        lines.append(
            f"    characterization: {_yaml_scalar(coordination.maker_characterization)}"
        )
    if coordination.reviewer_characterization:
        lines.append("  reviewer:")
        lines.append(
            f"    characterization: {_yaml_scalar(coordination.reviewer_characterization)}"
        )
    if smoke_command:
        lines.append(f"smoke_command: {_yaml_scalar(smoke_command)}")
    lines.extend(
        [
            "---",
            "",
            f"# {task_id}: {title}",
            "",
            "## Task",
            "",
            "Describe the change the agent should make.",
            "",
            "## Acceptance",
            "",
            "1. Describe the observable behavior that must be true.",
            "2. `test_commands` pass.",
            "3. `smoke_command` passes, if defined.",
            "4. Required coordination artifacts pass, if `coordination.mode` is "
            "`review` or `delegated`.",
            "",
            "## Handoff",
            "",
            "Commands run, failures seen, next hypothesis, and partial progress "
            "when stopping before completion.",
            "",
        ]
    )
    return "\n".join(lines)


def _yaml_list(items: list[str]) -> list[str]:
    return [f"  - {_yaml_scalar(item)}" for item in items]


def _yaml_scalar(value: str) -> str:
    return json.dumps(value)


def _filename_part(value: str, fallback: str, *, lowercase: bool = False) -> str:
    filename = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    if lowercase:
        filename = filename.lower()
    return filename or fallback


def _memory_template() -> str:
    return """# Agent Memory

Use this file for durable repo knowledge that helps future agent tasks.

Keep entries short and practical. Prefer updating existing repo docs or adding
a focused repo-local skill when the knowledge belongs somewhere more specific.
Do not store task-local subagent findings here unless they generalize beyond the
current task.

## Entries

- None yet.
"""


def _skills_readme_template() -> str:
    return """# Repo-Local Agent Skills

Optional reusable skills can live here:

```text
agent-docs/skills/<skill-name>/SKILL.md
```

The simplified runner does not auto-discover skills. Reference a skill from
`AGENTS.md`, a task body, or `read_first` when an agent should load it.

Create or update a skill only after a passed run reveals reusable workflow or
repo knowledge.

When a skill implies subagent work, the coordinator should still keep the
subagent brief and findings in the current run's `subagents/` directory.
"""


def _path_allowed(
    relative_changed: str,
    absolute_changed: str,
    allowed_paths: list[str],
    repo_root: Path,
) -> bool:
    for allowed in allowed_paths:
        normalized = allowed.replace("\\", "/")
        if Path(normalized).is_absolute():
            if fnmatch.fnmatch(absolute_changed, normalized):
                return True
            continue
        if fnmatch.fnmatch(relative_changed, normalized):
            return True
        if normalized.endswith("/**") and relative_changed == normalized[:-3]:
            return True
        candidate_abs = (repo_root / normalized).resolve().as_posix()
        if fnmatch.fnmatch(absolute_changed, candidate_abs):
            return True
    return False


def _new_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def _prompt(context: RunContext) -> str:
    task = context.task
    return f"""# Agent Task: {task.id} {task.title}

Read the task doc and listed context, then make the smallest correct change.

## Task Doc

{task.path}

## Read First

{_bullet(task.read_first)}

## Allowed Paths

{_bullet(task.allowed_paths)}

## Required Test Commands

{_bullet(task.test_commands)}

## Optional Smoke Command

{task.smoke_command or "None"}

## Coordination

{_coordination_prompt(task)}

## Session Handoff

Keep durable notes in:

{context.run_dir / "handoff.md"}

If using subagents, keep their briefs and findings in:

{context.run_dir / "subagents"}

## Verification

After editing, run:

```bash
python {Path(__file__).resolve()} {task.path} --repo-root {task.repo_root} --verify-only --run-dir {context.run_dir}
```
"""


def _subagents_readme(context: RunContext) -> str:
    task = context.task
    return f"""# Subagents: {context.task.id} {context.task.title}

Coordination mode: `{task.coordination.mode}`

Required artifacts:

{_required_artifact_bullets(task.coordination.mode)}

Use this directory only when a subagent is actually helpful or required by the
task's coordination mode.

The coordinator owns the run: it reads the task contract, invokes required
subagents, integrates accepted findings, runs the task commands, and runs final
verification. The runner remains the deterministic verifier.

When invoking a role, include the role characterization from the task metadata
as the first part of the brief. The characterization should describe the
relevant experience for this task, such as the domain, system type, scale,
language, or review specialty.

## Maker

The maker implements a bounded change inside assigned paths. The maker does not
decide final acceptance.

Characterization:

{_block_or_placeholder(task.coordination.maker_characterization)}

Use `maker.md` for delegated maker work:

```md
# Maker Brief

Characterization: <copy the task-specific maker characterization>
Task:
Allowed paths:
Files owned:
Required tests:

# Maker Result

Files changed:
Commands run:
Notes:
```

## Reviewer

The reviewer independently reviews the diff, tests, and artifacts. The reviewer
does not edit by default; it reports findings with evidence.

Characterization:

{_block_or_placeholder(task.coordination.reviewer_characterization)}

Use `reviewer.md` for required or optional review work:

```md
# Reviewer Brief

Characterization: <copy the task-specific reviewer characterization>
Task:
Diff/artifacts reviewed:
Focus areas:

# Reviewer Findings

- Severity:
  File:
  Issue:
  Evidence:
  Recommendation:

Verdict: approve | changes_requested
```

Each file should contain:

- the brief given to the subagent
- files or artifacts it reviewed
- findings, commands, and evidence
- recommended next action

For `review` and `delegated` modes, final verification requires
`subagents/reviewer.md` to contain an exact `Verdict: approve` line. The
coordinator owns final decisions and summarizes accepted findings back into
`../handoff.md`.
"""


def _handoff_template(context: RunContext) -> str:
    return f"""# Handoff: {context.task.id} {context.task.title}

## Current State

Not started.

## Commands Run

- None yet.

## Failures Seen

- None yet.

## Next Hypothesis

- None yet.

## Notes For Resume

- Run dir: `{context.run_dir}`
"""


def _write_run_json(context: RunContext, extra: dict[str, Any]) -> None:
    payload = {
        "run_id": context.run_id,
        "task_id": context.task.id,
        "task_path": str(context.task.path),
        "created_at": datetime.now(UTC).isoformat(),
        **extra,
    }
    _write_json(context.run_dir / "run.json", payload)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _coordination_prompt(task: TaskSpec) -> str:
    lines = [
        f"Mode: `{task.coordination.mode}`",
        "",
        "Required subagent artifacts:",
        _required_artifact_bullets(task.coordination.mode),
    ]
    if task.coordination.maker_characterization:
        lines.extend(
            [
                "",
                "Maker characterization:",
                "",
                _block_or_placeholder(task.coordination.maker_characterization),
            ]
        )
    if task.coordination.reviewer_characterization:
        lines.extend(
            [
                "",
                "Reviewer characterization:",
                "",
                _block_or_placeholder(task.coordination.reviewer_characterization),
            ]
        )
    if task.coordination.mode == "review":
        lines.extend(
            [
                "",
                "Invoke an independent reviewer before final verification.",
                "Final verification requires `subagents/reviewer.md` with "
                "`Verdict: approve`.",
            ]
        )
    elif task.coordination.mode == "delegated":
        lines.extend(
            [
                "",
                "Invoke a maker subagent for implementation and an independent "
                "reviewer before final verification.",
                "Final verification requires `subagents/maker.md` and "
                "`subagents/reviewer.md` with `Verdict: approve`.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "The coordinator may implement directly. Optional subagent work "
                "can still be recorded in `subagents/`.",
            ]
        )
    return "\n".join(lines)


def _required_artifact_bullets(mode: CoordinationMode) -> str:
    artifacts = _required_subagent_artifacts(mode)
    if not artifacts:
        return "- None"
    return "\n".join(f"- `subagents/{artifact}`" for artifact in artifacts)


def _block_or_placeholder(value: str | None) -> str:
    if not value:
        return "> Not required by this coordination mode."
    return f"> {value}"


def _bullet(items: list[str]) -> str:
    if not items:
        return "- None"
    return "\n".join(f"- `{item}`" for item in items)


def _decode_timeout_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _git_lines(repo_root: Path, command: list[str]) -> list[str]:
    completed = subprocess.run(
        command,
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _load_baseline_changed_files(run_dir: Path) -> list[str]:
    run_json = run_dir / "run.json"
    if not run_json.exists():
        return []
    try:
        payload = json.loads(run_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    baseline = payload.get("baseline_changed_files") or []
    return [str(path) for path in baseline] if isinstance(baseline, list) else []


def _run_subprocess(
    command: str,
    cwd: str | Path,
    *,
    label: str,
    timeout_seconds: int,
) -> CommandResult:
    start = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        return CommandResult(
            command=label,
            cwd=str(cwd),
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_seconds=round(time.monotonic() - start, 3),
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command=label,
            cwd=str(cwd),
            exit_code=124,
            stdout=_decode_timeout_output(exc.stdout),
            stderr=_decode_timeout_output(exc.stderr),
            duration_seconds=round(time.monotonic() - start, 3),
            timed_out=True,
        )


if __name__ == "__main__":
    sys.exit(main())
