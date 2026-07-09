# ABOUTME: Implements a small task runner for agent-docs tasks.
# ABOUTME: Verifies changed-file scope plus task-owned test and smoke commands.

from __future__ import annotations

import argparse
import dataclasses
import fnmatch
import json
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


class RunnerError(RuntimeError):
    """Base exception for local loop runner failures."""


class FrontmatterError(RunnerError):
    """Raised when task frontmatter is invalid."""


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
    parser = argparse.ArgumentParser(description="Prepare or verify an agent-docs task run.")
    parser.add_argument("task", help="Path to agent-docs/tasks/<task>.md")
    parser.add_argument("--repo-root", default=".", help="Repository root; defaults to cwd")
    parser.add_argument("--prepare-run", action="store_true", help="Generate prompt/run artifacts")
    parser.add_argument("--verify-only", action="store_true", help="Run verification gates")
    parser.add_argument("--run-dir", help="Existing run artifact directory for --verify-only")
    parser.add_argument("--timeout-seconds", type=int, default=1_800, help="Per-command timeout")
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve()
    try:
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
    return f"""# Subagents: {context.task.id} {context.task.title}

Use this directory only when a subagent is actually helpful.

For each subagent, create a short file named after the role or question, for
example:

```text
reviewer.md
research.md
api-investigation.md
```

Each file should contain:

- the brief given to the subagent
- files or artifacts it reviewed
- findings, commands, and evidence
- recommended next action

The parent agent owns final decisions. Summarize any accepted subagent findings
back into `../handoff.md`.
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
