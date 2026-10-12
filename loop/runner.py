# ABOUTME: Implements a small task runner for agent-docs tasks.
# ABOUTME: Discovers resumable runs and verifies task-owned completion gates.

from __future__ import annotations

import argparse
import dataclasses
import fnmatch
import json
import os
import re
import shlex
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Literal

import yaml

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loop.evidence import (
    EvidenceError, RepositorySnapshot, atomic_json, file_sha256, git_output,
    parse_snapshot, read_json_object, repository_snapshot, require_git_root,
)
from loop.process import capture_command

CoordinationMode = Literal["solo", "review", "delegated"]
ResumeAction = Literal["resume", "completed_context", "intake_required"]
VerificationStatus = Literal["passed", "failed", "missing", "invalid"]


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
class AcceptanceSpec:
    condition: str
    command: str
    evidence: str | None = None

    def to_json(self) -> dict[str, object]:
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
    acceptance: list[AcceptanceSpec] = field(default_factory=list)


@dataclass(frozen=True)
class CommandResult:
    command: str
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False

    def to_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class RunContext:
    task: TaskSpec
    run_id: str
    run_dir: Path


@dataclass(frozen=True)
class ResumeResult:
    action: ResumeAction
    repo_root: str
    task_id: str | None
    task_path: str | None
    run_id: str | None
    run_dir: str | None
    prompt: str | None
    handoff: str | None
    verification: str | None
    verification_status: VerificationStatus | None
    warnings: list[str]

    def to_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class _ResumeCandidate:
    created_at: datetime
    result: ResumeResult


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
    binding: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "status": self.status,
            "gates": [gate.to_json() for gate in self.gates],
            "commands": [command.to_json() for command in self.commands],
            "binding": self.binding,
        }


def _repo_path(path: str | Path, root: Path) -> Path:
    candidate = Path(path)
    return (candidate if candidate.is_absolute() else root / candidate).resolve()


def load_task(task_path: str | Path, repo_root: str | Path) -> TaskSpec:
    root = Path(repo_root).resolve()
    task_file = _repo_path(task_path, root)
    frontmatter, _ = _read_frontmatter(task_file)

    required = ["id", "title", "allowed_paths", "test_commands"]
    missing = [key for key in required if key not in frontmatter]
    if missing:
        raise FrontmatterError(f"{task_file} missing required frontmatter: {', '.join(missing)}")

    task_id = _required_text(frontmatter["id"], "id")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", task_id):
        raise FrontmatterError("id must be a single safe path component")
    commands = _string_list(frontmatter["test_commands"], "test_commands")
    smoke_command = frontmatter.get("smoke_command")
    smoke = _required_text(smoke_command, "smoke_command") if smoke_command is not None else None
    return TaskSpec(
        path=task_file,
        repo_root=root,
        id=task_id,
        title=_required_text(frontmatter["title"], "title"),
        allowed_paths=_string_list(frontmatter["allowed_paths"], "allowed_paths"),
        read_first=_string_list(frontmatter.get("read_first", []), "read_first"),
        test_commands=commands,
        smoke_command=smoke,
        coordination=_coordination_spec(frontmatter.get("coordination")),
        acceptance=_acceptance_specs(frontmatter.get("acceptance"), commands, smoke),
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


def run_command(command: str, cwd: str | Path, timeout_seconds: float = 1_800) -> CommandResult:
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
    acceptance: list[AcceptanceSpec] | None = None,
    overwrite: bool = False,
) -> Path:
    root = Path(repo_root).resolve()
    clean_task_id = task_id.strip()
    clean_title = title.strip()
    if not clean_task_id:
        raise FrontmatterError("task id is required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", clean_task_id):
        raise FrontmatterError("task id must be a single safe path component")
    if not clean_title:
        raise FrontmatterError("task title is required")
    if not allowed_paths:
        raise FrontmatterError("--allowed-path is required when creating a task")
    if not test_commands:
        raise FrontmatterError("--test-command is required when creating a task")
    if acceptance:
        _acceptance_specs([item.to_json() for item in acceptance], test_commands, smoke_command)

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
            acceptance=acceptance or [],
        ),
        encoding="utf-8",
    )
    return task_path


def prepare_run(task: TaskSpec, repo_root: str | Path) -> RunContext:
    root = Path(repo_root).resolve()
    _validate_task_contract(task, root)
    run_id = _new_run_id()
    run_dir = root / "agent-docs" / "runs" / task.id / run_id
    if not _is_within(run_dir.resolve(), root):
        raise RunnerError("run directory escapes the repository")
    baseline = _snapshot(root, run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    subagents_dir = run_dir / "subagents"
    subagents_dir.mkdir()

    context = RunContext(task=task, run_id=run_id, run_dir=run_dir)
    (run_dir / "prompt.md").write_text(_prompt(context), encoding="utf-8")
    (run_dir / "handoff.md").write_text(_handoff_template(context), encoding="utf-8")
    (subagents_dir / "README.md").write_text(_subagents_readme(context), encoding="utf-8")
    (run_dir / "task.snapshot.md").write_bytes(task.path.read_bytes())
    _write_run_json(
        context,
        {
            "status": "prepared",
            "schema_version": 2,
            "repo_root": str(root),
            "task_sha256": file_sha256(task.path),
            "baseline": baseline.to_json(),
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


def discover_resume(repo_root: str | Path) -> ResumeResult:
    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise RunnerError(f"repository root is not a directory: {root}")

    warnings: list[str] = []
    runs_root = (root / "agent-docs" / "runs").resolve()
    if not _is_within(runs_root, root):
        warnings.append("Skipped agent-docs/runs because it escapes the repository")
        return _empty_resume_result(root, warnings)
    candidates: list[_ResumeCandidate] = []
    if runs_root.is_dir():
        for run_json in sorted(runs_root.glob("*/*/run.json")):
            candidate = _resume_candidate(run_json, root, runs_root, warnings)
            if candidate is not None:
                candidates.append(candidate)

    if not candidates:
        return _empty_resume_result(root, warnings)

    # Preparing a replacement is the explicit migration/retry boundary for a task.
    # Retain older artifacts, but do not resurrect superseded failed/legacy attempts.
    latest: dict[str, _ResumeCandidate] = {}
    for candidate in candidates:
        task_id = candidate.result.task_id
        assert task_id is not None
        previous = latest.get(task_id)
        if previous is None or _resume_sort_key(candidate) > _resume_sort_key(previous):
            latest[task_id] = candidate
    candidates = list(latest.values())
    unfinished = [
        candidate
        for candidate in candidates
        if candidate.result.verification_status != "passed"
    ]
    selected = max(unfinished or candidates, key=_resume_sort_key).result
    if selected.verification_status == "passed":
        assert selected.task_path is not None and selected.run_dir is not None
        task = load_task(selected.task_path, root)
        try:
            _validate_current_verification(task, root, Path(selected.run_dir))
        except (RunnerError, EvidenceError, OSError) as exc:
            warnings.append(f"Selected verification is stale or invalid: {exc}")
            selected = dataclasses.replace(selected, action="resume", verification_status="invalid")
    return dataclasses.replace(selected, warnings=warnings)


def verify_task(
    task: TaskSpec,
    repo_root: str | Path,
    run_dir: str | Path,
    *,
    command_timeout_seconds: int = 1_800,
) -> VerificationResult:
    root = Path(repo_root).resolve()
    output_dir = _repo_path(run_dir, root)
    baseline = _validate_prepared(task, root, output_dir)
    if command_timeout_seconds <= 0:
        raise RunnerError("command timeout must be positive")
    with _artifact_lock(output_dir):
        before = _snapshot(root, output_dir)
        before_binding = _binding(task, output_dir, before)
        # An interrupted attempt must never leave an earlier passing result current.
        _write_json(output_dir / "verification.json", {
            "schema_version": 2, "status": "running", "binding": before_binding,
        })
        test_results = [
            run_command(command, root, timeout_seconds=command_timeout_seconds)
            for command in task.test_commands
        ]
        commands = list(test_results)
        _write_json(output_dir / "tests.json", [result.to_json() for result in test_results])
        smoke_result = (
            run_command(task.smoke_command, root, timeout_seconds=command_timeout_seconds)
            if task.smoke_command else None
        )
        if smoke_result is not None:
            commands.append(smoke_result)
        _write_json(output_dir / "smoke.json", smoke_result.to_json() if smoke_result else None)
        # Commands may generate files, format code or mutate fixtures. Verify their final state.
        after = _snapshot(root, output_dir)
        binding = _binding(task, output_dir, after)
        changed_files = after.changes_since(baseline)
        violations = check_allowed_paths(changed_files, task.allowed_paths, root)
        scope = GateResult(name="diff_scope", passed=not violations, details={
            "changed_files": changed_files, "violations": violations,
            "baseline_head": baseline.head, "current_head": after.head,
        })
        coordination = _coordination_gate(task, output_dir, binding=binding)
        _write_json(output_dir / "coordination.json", coordination.to_json())
        stability = GateResult(name="snapshot_stability", passed=before_binding == binding, details={
            "before": before_binding, "after": binding,
            "error": None if before_binding == binding else "commands changed the reviewed/tested snapshot; rerun verification",
        })
        gates = [
            scope, coordination,
            GateResult(name="tests", passed=bool(test_results) and all(item.exit_code == 0 for item in test_results), details={"count": len(test_results)}),
            GateResult(name="smoke", passed=smoke_result is None or smoke_result.exit_code == 0, details=(
                {"command": smoke_result.command, "exit_code": smoke_result.exit_code}
                if smoke_result else {"skipped": True, "reason": "no smoke_command configured"}
            )),
            stability, _acceptance_gate(task, root, commands),
        ]
        # Check the immutable contract again in case a command edited it.
        try:
            _validate_prepared(task, root, output_dir)
        except RunnerError as exc:
            gates.append(GateResult(name="task_snapshot", passed=False, details={"error": str(exc)}))
        status = "passed" if all(item.passed for item in gates) else "failed"
        result = VerificationResult(status=status, gates=gates, commands=commands, binding=binding)
        _write_json(output_dir / "verification.json", result.to_json())
        return result


def record_review(task: TaskSpec, repo_root: str | Path, run_dir: str | Path) -> dict[str, str]:
    """Seal the existing verdict to the inspected snapshot; this does not prove independence."""
    root = Path(repo_root).resolve()
    output_dir = _repo_path(run_dir, root)
    _validate_prepared(task, root, output_dir)
    with _artifact_lock(output_dir):
        artifact = output_dir / "subagents" / "reviewer.md"
        if not _is_safe_file(artifact, output_dir):
            raise RunnerError("a safe subagents/reviewer.md artifact is required")
        try:
            verdict = _reviewer_verdict(artifact.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            raise RunnerError(f"cannot read reviewer artifact: {exc}") from exc
        if verdict not in {"approve", "changes_requested"}:
            raise RunnerError("reviewer artifact must contain Verdict: approve or changes_requested")
        binding = _binding(task, output_dir, _snapshot(root, output_dir))
        payload = {**binding, "reviewer_sha256": file_sha256(artifact), "verdict": verdict}
        _write_json(output_dir / "review.json", {"schema_version": 2, **payload})
        return payload


def collect_changed_files(repo_root: str | Path) -> list[str]:
    root = Path(repo_root).resolve()
    try:
        require_git_root(root)
    except EvidenceError as exc:
        raise RunnerError(str(exc)) from exc
    tracked = _git_lines(root, ["git", "diff", "--name-only", "-z"])
    staged = _git_lines(root, ["git", "diff", "--cached", "--name-only", "-z"])
    untracked = _git_lines(root, ["git", "ls-files", "--others", "--exclude-standard", "-z"])
    return sorted(set(tracked + staged + untracked))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover, create, prepare, or verify an agent-docs task run."
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
    parser.add_argument("--acceptance-condition", action="append", default=[], help="Observable acceptance condition (paired with --acceptance-command)")
    parser.add_argument("--acceptance-command", action="append", default=[], help="Declared test/smoke command proving the corresponding condition")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing generated task")
    parser.add_argument("--prepare-run", action="store_true", help="Generate prompt/run artifacts")
    parser.add_argument("--verify-only", action="store_true", help="Run verification gates")
    parser.add_argument("--record-review", action="store_true", help="Bind the existing reviewer artifact to the current task and tree")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Discover the target repository's resumable Agent Core run",
    )
    parser.add_argument("--run-dir", help="Existing run artifact directory for --verify-only")
    parser.add_argument("--timeout-seconds", type=int, default=1_800, help="Per-command timeout")
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve()
    try:
        if args.resume:
            incompatible = any(
                [
                    args.task,
                    args.new_task,
                    args.prepare_run,
                    args.verify_only,
                    args.record_review,
                    args.run_dir,
                ]
            )
            if incompatible:
                parser.error(
                    "--resume cannot be combined with a task, --new-task, "
                    "--prepare-run, --verify-only, or --run-dir"
                )
            print(json.dumps(discover_resume(root).to_json(), indent=2, sort_keys=True))
            return 0

        if args.new_task:
            if args.task:
                parser.error("task path cannot be provided with --new-task")
            if not args.title:
                parser.error("--title is required with --new-task")
            if len(args.acceptance_condition) != len(args.acceptance_command):
                parser.error("pair every --acceptance-condition with an --acceptance-command")
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
                acceptance=[AcceptanceSpec(condition, command) for condition, command in zip(args.acceptance_condition, args.acceptance_command)],
                overwrite=args.force,
            )
            print(f"task={task_path}")
            return 0

        if not args.task:
            parser.error("task path is required unless --new-task or --resume is used")
        task = load_task(args.task, root)

        if args.record_review:
            if args.verify_only or args.prepare_run or not args.run_dir:
                parser.error("--record-review requires --run-dir and cannot combine with --verify-only or --prepare-run")
            print(json.dumps(record_review(task, root, args.run_dir), indent=2, sort_keys=True))
            return 0

        if args.verify_only:
            if not args.run_dir:
                parser.error("--verify-only requires a prepared --run-dir")
            run_dir = _repo_path(args.run_dir, root)
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


def _resume_candidate(
    run_json: Path,
    repo_root: Path,
    runs_root: Path,
    warnings: list[str],
) -> _ResumeCandidate | None:
    label = _display_path(run_json, repo_root)
    run_dir = run_json.parent.resolve()
    if not _is_within(run_dir, runs_root) or not _is_safe_file(run_json, run_dir):
        warnings.append(f"Skipped unsafe run metadata: {label}")
        return None

    try:
        payload = json.loads(run_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        warnings.append(f"Skipped malformed run metadata {label}: {exc}")
        return None
    if not isinstance(payload, dict):
        warnings.append(f"Skipped malformed run metadata {label}: expected an object")
        return None

    legacy = payload.get("schema_version") != 2
    if legacy:
        warnings.append(f"Legacy run {label} has no v2 content baseline; retain its context and prepare a new v2 run")

    run_id = _required_metadata_string(payload, "run_id")
    task_id = _required_metadata_string(payload, "task_id")
    task_value = _required_metadata_string(payload, "task_path")
    created_value = _required_metadata_string(payload, "created_at")
    if None in (run_id, task_id, task_value, created_value):
        warnings.append(f"Skipped malformed run metadata {label}: missing string fields")
        return None
    assert run_id is not None
    assert task_id is not None
    assert task_value is not None
    assert created_value is not None
    if run_id != run_dir.name or task_id != run_dir.parent.name:
        warnings.append(f"Skipped inconsistent run metadata: {label}")
        return None

    try:
        created_at = datetime.fromisoformat(created_value)
    except ValueError:
        warnings.append(f"Skipped malformed run metadata {label}: invalid created_at")
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    created_at = created_at.astimezone(UTC)

    task_path = Path(task_value)
    if not task_path.is_absolute():
        task_path = repo_root / task_path
    task_path = task_path.resolve()
    tasks_root = (repo_root / "agent-docs" / "tasks").resolve()
    if (
        not _is_within(tasks_root, repo_root)
        or not _is_within(task_path, tasks_root)
        or not task_path.is_file()
    ):
        warnings.append(f"Skipped unsafe or missing task path in {label}")
        return None
    try:
        task = load_task(task_path, repo_root)
    except (RunnerError, OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        warnings.append(f"Skipped invalid task for {label}: {exc}")
        return None
    if task.id != task_id:
        warnings.append(f"Skipped inconsistent task metadata: {label}")
        return None

    prompt = run_dir / "prompt.md"
    handoff = run_dir / "handoff.md"
    if not _is_safe_file(prompt, run_dir) or not _is_safe_file(handoff, run_dir):
        warnings.append(f"Skipped run with unsafe or missing artifacts: {label}")
        return None

    verification = run_dir / "verification.json"
    verification_status = _verification_status(verification, run_dir, label, warnings)
    if verification_status is None:
        return None
    if legacy:
        verification_status = "invalid"
    action: ResumeAction = (
        "completed_context" if verification_status == "passed" else "resume"
    )
    result = ResumeResult(
        action=action,
        repo_root=str(repo_root),
        task_id=task_id,
        task_path=str(task_path),
        run_id=run_id,
        run_dir=str(run_dir),
        prompt=str(prompt),
        handoff=str(handoff),
        verification=str(verification),
        verification_status=verification_status,
        warnings=[],
    )
    return _ResumeCandidate(created_at=created_at, result=result)


def _verification_status(
    verification: Path,
    run_dir: Path,
    run_label: str,
    warnings: list[str],
) -> VerificationStatus | None:
    if not verification.exists():
        return "missing"
    if not _is_safe_file(verification, run_dir):
        warnings.append(f"Skipped run with unsafe verification artifact: {run_label}")
        return None
    try:
        payload = json.loads(verification.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        warnings.append(f"Invalid verification artifact for {run_label}: {exc}")
        return "invalid"
    if not isinstance(payload, dict) or payload.get("status") not in {"passed", "failed"}:
        warnings.append(f"Invalid verification status for {run_label}")
        return "invalid"
    binding = payload.get("binding")
    gates = payload.get("gates")
    commands = payload.get("commands")
    if (
        payload.get("schema_version") != 2
        or not isinstance(binding, dict)
        or not all(isinstance(binding.get(key), str) for key in ("task_sha256", "tree_sha256", "run_id"))
        or not isinstance(gates, list) or not gates
        or not all(isinstance(gate, dict) and isinstance(gate.get("passed"), bool) for gate in gates)
        or not isinstance(commands, list) or not commands
        or not all(isinstance(command, dict) and isinstance(command.get("command"), str)
                   and type(command.get("exit_code")) is int for command in commands)
        or (payload["status"] == "passed" and not all(gate["passed"] for gate in gates))
    ):
        warnings.append(f"Unbound or inconsistent verification artifact for {run_label}; prepare a v2 run for legacy artifacts")
        return "invalid"
    status = payload["status"]
    return "passed" if status == "passed" else "failed"


def _empty_resume_result(repo_root: Path, warnings: list[str]) -> ResumeResult:
    return ResumeResult(
        action="intake_required",
        repo_root=str(repo_root),
        task_id=None,
        task_path=None,
        run_id=None,
        run_dir=None,
        prompt=None,
        handoff=None,
        verification=None,
        verification_status=None,
        warnings=warnings,
    )


def _resume_sort_key(candidate: _ResumeCandidate) -> tuple[datetime, str, str]:
    result = candidate.result
    return (candidate.created_at, result.run_id or "", result.run_dir or "")


def _required_metadata_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _is_safe_file(path: Path, parent: Path) -> bool:
    return path.is_file() and _is_within(path.resolve(), parent.resolve())


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return str(path)


def _read_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise FrontmatterError(f"cannot read task frontmatter {path}: {exc}") from exc
    if not text.startswith("---\n"):
        raise FrontmatterError(f"{path} does not start with YAML frontmatter")
    parts = text.split("---\n", 2)
    if len(parts) != 3:
        raise FrontmatterError(f"{path} has an unterminated YAML frontmatter block")
    try:
        raw = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        raise FrontmatterError(f"invalid YAML frontmatter in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise FrontmatterError(f"{path} frontmatter must be a mapping")
    return raw, parts[2]


def _string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise FrontmatterError(f"{field_name} must be a list, got {type(value).__name__}")
    return [_required_text(item, field_name) for item in value]


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FrontmatterError(f"{field_name} must be a nonempty string")
    return value.strip()


def _acceptance_specs(value: object, commands: list[str], smoke: str | None) -> list[AcceptanceSpec]:
    if value is None:
        return []  # Legacy task documents remain readable, but cannot prepare v2 runs.
    if not isinstance(value, list) or not value:
        raise FrontmatterError("acceptance must contain at least one condition/command mapping")
    declared = {*commands, *([smoke] if smoke else [])}
    acceptance: list[AcceptanceSpec] = []
    for item in value:
        if not isinstance(item, dict):
            raise FrontmatterError("each acceptance entry must be a mapping")
        condition = _required_text(item.get("condition"), "acceptance.condition")
        command = _required_text(item.get("command"), "acceptance.command")
        if command not in declared:
            raise FrontmatterError("acceptance.command must match a declared test_commands or smoke_command")
        if condition.lower() in {"todo", "tbd", "describe the observable behavior that must be true."}:
            raise FrontmatterError("acceptance.condition must describe observable behavior")
        evidence = item.get("evidence")
        acceptance.append(AcceptanceSpec(condition, command, _required_text(evidence, "acceptance.evidence") if evidence is not None else None))
    return acceptance


def _validate_task_contract(task: TaskSpec, root: Path) -> None:
    if task.repo_root != root or not _is_within(task.path, root / "agent-docs" / "tasks"):
        raise RunnerError("task must belong to this repository's agent-docs/tasks directory")
    if task != load_task(task.path, root):
        raise RunnerError("task spec differs from the task document; reload the task")
    if not task.allowed_paths or not task.test_commands:
        raise FrontmatterError("allowed_paths and test_commands must not be empty")
    if not task.acceptance:
        raise FrontmatterError("acceptance condition/command mappings are required for v2 runs; update legacy task docs")


def _snapshot(root: Path, run_dir: Path) -> RepositorySnapshot:
    try:
        return repository_snapshot(root, exclude=[run_dir])
    except (EvidenceError, OSError) as exc:
        raise RunnerError(str(exc)) from exc


def _binding(task: TaskSpec, run_dir: Path, snapshot: RepositorySnapshot) -> dict[str, str]:
    task_relative = task.path.relative_to(task.repo_root).as_posix()
    code = RepositorySnapshot(snapshot.head, {path: value for path, value in snapshot.files.items() if path != task_relative})
    return {"task_sha256": file_sha256(task.path), "tree_sha256": code.sha256, "run_id": run_dir.name}


def _validate_prepared(task: TaskSpec, root: Path, output_dir: Path) -> RepositorySnapshot:
    expected_parent = root / "agent-docs" / "runs" / task.id
    if output_dir.parent != expected_parent or not _is_safe_file(output_dir / "run.json", output_dir):
        raise RunnerError("verification requires a prepared run directory and baseline; use --prepare-run")
    try:
        metadata = read_json_object(output_dir / "run.json")
        if metadata.get("schema_version") != 2:
            raise RunnerError("legacy run lacks content baseline; retain its context and prepare a new v2 run")
        if metadata.get("repo_root") != str(root) or metadata.get("task_id") != task.id or metadata.get("task_path") != str(task.path) or metadata.get("run_id") != output_dir.name:
            raise RunnerError("prepared run/task/repository metadata does not match")
        snapshot_file = output_dir / "task.snapshot.md"
        if not _is_safe_file(snapshot_file, output_dir):
            raise RunnerError("prepared task snapshot is missing or unsafe")
        digest = metadata.get("task_sha256")
        if digest != file_sha256(task.path) or digest != file_sha256(snapshot_file):
            raise RunnerError("task changed since preparation; restore the snapshot or explicitly prepare a new run")
        _validate_task_contract(task, root)
        return parse_snapshot(metadata.get("baseline"))
    except EvidenceError as exc:
        raise RunnerError(str(exc)) from exc


@contextmanager
def _artifact_lock(output_dir: Path) -> Iterator[None]:
    lock_path = output_dir / ".verification.lock"
    if lock_path.exists() and not _is_safe_file(lock_path, output_dir):
        raise RunnerError("unsafe verification lock")
    with lock_path.open("a+b") as stream:
        try:
            if os.name == "posix":
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RunnerError("another verification or review recording owns this run") from exc
        try:
            yield
        finally:
            if os.name == "posix":
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            else:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def _acceptance_gate(task: TaskSpec, root: Path, commands: list[CommandResult]) -> GateResult:
    results = {item.command: item for item in commands}
    conditions: list[dict[str, object]] = []
    for acceptance in task.acceptance:
        command = results.get(acceptance.command)
        entry: dict[str, object] = {"condition": acceptance.condition, "command": acceptance.command, "passed": command is not None and command.exit_code == 0}
        if acceptance.evidence:
            artifact = (root / acceptance.evidence).resolve()
            if not _is_within(artifact, root) or not artifact.is_file() or artifact.stat().st_size == 0:
                entry.update(passed=False, error="acceptance evidence must be a nonempty file inside the repository")
            else:
                entry.update(evidence=acceptance.evidence, evidence_sha256=file_sha256(artifact))
        conditions.append(entry)
    return GateResult(name="acceptance", passed=bool(conditions) and all(item["passed"] is True for item in conditions), details={"conditions": conditions})


def _validate_current_verification(task: TaskSpec, root: Path, run_dir: Path) -> None:
    _validate_prepared(task, root, run_dir)
    payload = read_json_object(run_dir / "verification.json")
    binding = _binding(task, run_dir, _snapshot(root, run_dir))
    if payload.get("binding") != binding:
        raise RunnerError("verification is for a different task or code snapshot")
    gates = payload.get("gates")
    if not isinstance(gates, list):
        raise RunnerError("verification gates are missing")
    expected_gates = {"diff_scope", "coordination", "tests", "smoke", "snapshot_stability", "acceptance"}
    if {item.get("name") for item in gates if isinstance(item, dict)} != expected_gates:
        raise RunnerError("verification gate set is incomplete")
    expected_commands = task.test_commands + ([task.smoke_command] if task.smoke_command else [])
    command_payloads = payload.get("commands")
    if not isinstance(command_payloads, list) or [item.get("command") for item in command_payloads if isinstance(item, dict)] != expected_commands:
        raise RunnerError("verification commands do not match the task")
    if any(not isinstance(item, dict) or item.get("exit_code") != 0 for item in command_payloads):
        raise RunnerError("passing verification includes a failed command")
    coordination = _coordination_gate(task, run_dir, binding=binding)
    if not coordination.passed:
        raise RunnerError("review evidence changed after verification")
    acceptance = next(item for item in gates if isinstance(item, dict) and item.get("name") == "acceptance")
    replay = [CommandResult(command, str(root), 0, "", "", 0) for command in expected_commands]
    if acceptance.get("details") != _acceptance_gate(task, root, replay).details:
        raise RunnerError("acceptance evidence changed after verification")


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


def _coordination_gate(task: TaskSpec, output_dir: Path, *, binding: dict[str, str] | None = None) -> GateResult:
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
        if not _is_safe_file(path, output_dir):
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
        if passed:
            try:
                review = read_json_object(output_dir / "review.json")
                valid = review.get("schema_version") == 2 and binding is not None and all(review.get(key) == value for key, value in binding.items())
                valid = valid and review.get("reviewer_sha256") == file_sha256(subagents_dir / "reviewer.md") and review.get("verdict") == reviewer_verdict
                if not valid:
                    raise EvidenceError("review does not match the current task, code or reviewer artifact")
            except (EvidenceError, OSError) as exc:
                passed = False
                details["error"] = f"record current review with --record-review: {exc}"

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
    acceptance: list[AcceptanceSpec],
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
    if acceptance:
        lines.append("acceptance:")
        for criterion in acceptance:
            lines.extend([f"  - condition: {_yaml_scalar(criterion.condition)}", f"    command: {_yaml_scalar(criterion.command)}"])
            if criterion.evidence:
                lines.append(f"    evidence: {_yaml_scalar(criterion.evidence)}")
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
    memory_paths = [name for name in ("AGENTS.md", "agent-docs/MEMORY.md", "agent-docs/skills/README.md")
                    if _is_safe_file(task.repo_root / name, task.repo_root)]
    read_first = list(dict.fromkeys([*memory_paths, *task.read_first]))
    base = [sys.executable, str(Path(__file__).with_name("run_task.py").resolve()),
            str(task.path), "--repo-root", str(task.repo_root)]
    verify_command = shlex.join([*base, "--verify-only", "--run-dir", str(context.run_dir)])
    review_command = shlex.join([*base, "--record-review", "--run-dir", str(context.run_dir)])
    acceptance = "\n".join(f"- {item.condition}: `{item.command}`" + (f"; evidence: `{item.evidence}`" if item.evidence else "") for item in task.acceptance)
    return f"""# Agent Task: {task.id} {task.title}

Read the task doc and listed context, then make the smallest correct change.

## Task Doc

{task.path}

Immutable prepared copy: {context.run_dir / 'task.snapshot.md'}

Do not revise the task contract during execution. An intentional scope change
requires an explicitly revised task and a new prepared run; preserve the old run.

## Read First

{_bullet(read_first)}

Read relevant durable memory and the local skill index. Follow indexed skills
when they apply; do not load unrelated history.

## Allowed Paths

{_bullet(task.allowed_paths)}

## Required Test Commands

{_bullet(task.test_commands)}

## Optional Smoke Command

{task.smoke_command or "None"}

## Acceptance Evidence

{acceptance}

The runner records whether each mapped command passes and hashes optional
evidence files. These gates do not prove requirements beyond the declared checks.

## Coordination

{_coordination_prompt(task)}

## Session Handoff

Keep durable notes in:

{context.run_dir / "handoff.md"}

If using subagents, keep their briefs and findings in:

{context.run_dir / "subagents"}

## Simplify And Review

Inspect the patch for unnecessary complexity and duplication. Use the client's
native simplify action when useful and available; no external CLI or model is
required. Include resulting edits in the required review.

After a reviewer inspects the final patch and writes `subagents/reviewer.md`,
bind that artifact to the current task and code (required for review/delegated):

```bash
{review_command}
```

This records artifact freshness; it cannot prove reviewer independence. Any
subsequent code or reviewer-artifact changes require fresh review and recording.

## Verification

Use focused regression commands for red/green work. The final runner executes
declared test and smoke commands, so do not duplicate a complete verification
run immediately beforehand. After editing and required review, run:

```bash
{verify_command}
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
    atomic_json(path, payload)


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


def _git_lines(repo_root: Path, command: list[str]) -> list[str]:
    try:
        return [os.fsdecode(line) for line in git_output(repo_root, command[1:]).split(b"\0") if line]
    except EvidenceError as exc:
        raise RunnerError(str(exc)) from exc


def _run_subprocess(
    command: str,
    cwd: str | Path,
    *,
    label: str,
    timeout_seconds: float,
) -> CommandResult:
    try:
        result = capture_command(command, Path(cwd), timeout_seconds)
    except (OSError, ValueError) as exc:
        raise RunnerError(f"could not run command {label}: {exc}") from exc
    return CommandResult(command=label, cwd=str(cwd), **dataclasses.asdict(result))


if __name__ == "__main__":
    sys.exit(main())
