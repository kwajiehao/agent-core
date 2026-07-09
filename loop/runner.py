# ABOUTME: Implements the local agent-docs task loop runner and verification gates.
# ABOUTME: Keeps final acceptance tied to runner-owned evidence, not maker summaries.

from __future__ import annotations

import argparse
import dataclasses
import fnmatch
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import yaml

# Role skills ship with agent-core; a repo-local skill with the same name
# overrides the shipped one.
CORE_SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"
ROLE_SKILL_NAMES = {
    "agent-docs-loop",
    "agent-docs-maker",
    "agent-docs-verifier",
    "agent-docs-reflection",
}


class RunnerError(RuntimeError):
    """Base exception for local loop runner failures."""


class FrontmatterError(RunnerError):
    """Raised when a task or skill frontmatter block is invalid."""


class MissingSmokeScript(RunnerError):
    """Raised when the runner cannot identify a mandatory smoke script."""


class AmbiguousSmokeScript(RunnerError):
    """Raised when more than one smoke script could satisfy a task."""


class ProjectConfigError(RunnerError):
    """Raised when agent-docs/loop.yaml is invalid."""


@dataclass(frozen=True)
class LoopConfig:
    max_attempts: int = 3
    max_no_progress_attempts: int = 2
    max_wall_minutes: int = 120
    maker_token_budget: int = 80_000
    verifier_token_budget: int = 30_000
    reflection_token_budget: int = 10_000
    skills: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "LoopConfig":
        raw = raw or {}
        defaults = dataclasses.asdict(DEFAULT_LOOP_CONFIG)
        merged = {**defaults, **raw}
        skills = merged.get("skills") or []
        if not isinstance(skills, list):
            raise FrontmatterError("loop.skills must be a list")
        merged["skills"] = [str(skill) for skill in skills]
        return cls(
            max_attempts=int(merged["max_attempts"]),
            max_no_progress_attempts=int(merged["max_no_progress_attempts"]),
            max_wall_minutes=int(merged["max_wall_minutes"]),
            maker_token_budget=int(merged["maker_token_budget"]),
            verifier_token_budget=int(merged["verifier_token_budget"]),
            reflection_token_budget=int(merged["reflection_token_budget"]),
            skills=merged["skills"],
        )


DEFAULT_LOOP_CONFIG = LoopConfig()


@dataclass(frozen=True)
class ServiceConfig:
    name: str
    command: str
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    health_url: str | None = None
    health_headers: dict[str, str] = field(default_factory=dict)
    background: bool = False
    startup_timeout_seconds: int = 120


@dataclass(frozen=True)
class ProjectConfig:
    api_key_env: str | None = None
    services: list[ServiceConfig] = field(default_factory=list)


def load_project_config(repo_root: str | Path) -> ProjectConfig:
    path = Path(repo_root).resolve() / "agent-docs" / "loop.yaml"
    if not path.exists():
        return ProjectConfig()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ProjectConfigError(f"{path} must be a YAML mapping")
    services_raw = raw.get("services") or []
    if not isinstance(services_raw, list):
        raise ProjectConfigError(f"{path}: services must be a list")
    api_key_env = raw.get("api_key_env")
    return ProjectConfig(
        api_key_env=str(api_key_env) if api_key_env is not None else None,
        services=[_service_config(path, entry) for entry in services_raw],
    )


def _service_config(path: Path, entry: Any) -> ServiceConfig:
    if not isinstance(entry, dict):
        raise ProjectConfigError(f"{path}: each service must be a mapping")
    name = entry.get("name")
    command = entry.get("command")
    if not name or not command:
        raise ProjectConfigError(f"{path}: each service needs `name` and `command`")
    env = entry.get("env") or {}
    health_headers = entry.get("health_headers") or {}
    if not isinstance(env, dict) or not isinstance(health_headers, dict):
        raise ProjectConfigError(
            f"{path}: service `{name}` env and health_headers must be mappings"
        )
    return ServiceConfig(
        name=str(name),
        command=str(command),
        cwd=str(entry["cwd"]) if entry.get("cwd") is not None else None,
        env={str(key): str(value) for key, value in env.items()},
        health_url=str(entry["health_url"]) if entry.get("health_url") is not None else None,
        health_headers={str(key): str(value) for key, value in health_headers.items()},
        background=bool(entry.get("background", False)),
        startup_timeout_seconds=int(entry.get("startup_timeout_seconds", 120)),
    )


@dataclass(frozen=True)
class TaskSpec:
    path: Path
    repo_root: Path
    body: str
    frontmatter: dict[str, Any]
    id: str
    title: str
    status: str
    depends_on: list[str]
    change_type: str | None
    allowed_paths: list[str]
    read_first: list[str]
    test_commands: list[str]
    rollback: str
    loop: LoopConfig


@dataclass(frozen=True)
class SkillSummary:
    name: str
    description: str
    path: Path
    explicit: bool


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
    smoke_script: Path
    skills: list[SkillSummary]
    prepare_only: bool


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
    frontmatter, body = _read_frontmatter(task_file)

    required = [
        "id",
        "title",
        "status",
        "allowed_paths",
        "read_first",
        "rollback",
    ]
    missing = [key for key in required if key not in frontmatter]
    if missing:
        raise FrontmatterError(f"{task_file} missing required frontmatter: {', '.join(missing)}")

    return TaskSpec(
        path=task_file,
        repo_root=root,
        body=body,
        frontmatter=frontmatter,
        id=str(frontmatter["id"]),
        title=str(frontmatter["title"]),
        status=str(frontmatter["status"]),
        depends_on=_string_list(frontmatter.get("depends_on", [])),
        change_type=str(frontmatter["change_type"]) if frontmatter.get("change_type") is not None else None,
        allowed_paths=_string_list(frontmatter["allowed_paths"]),
        read_first=_string_list(frontmatter["read_first"]),
        test_commands=_string_list(frontmatter.get("test_commands", [])),
        rollback=str(frontmatter["rollback"]),
        loop=LoopConfig.from_mapping(frontmatter.get("loop")),
    )


def discover_skills(repo_root: str | Path, task: TaskSpec) -> list[SkillSummary]:
    skills_dir = Path(repo_root).resolve() / "agent-docs" / "skills"
    if not skills_dir.exists():
        return []

    explicit = set(task.loop.skills)
    task_tokens = _keywords(
        " ".join(
            [
                task.id,
                task.title,
                task.change_type or "",
                " ".join(task.read_first),
                " ".join(task.allowed_paths),
            ]
        )
    )
    matches: list[SkillSummary] = []

    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        try:
            frontmatter, _ = _read_frontmatter(skill_md)
        except FrontmatterError:
            continue
        name = str(frontmatter.get("name") or skill_md.parent.name)
        description = str(frontmatter.get("description") or "")
        is_explicit = name in explicit or skill_md.parent.name in explicit
        if name in ROLE_SKILL_NAMES and not is_explicit:
            continue
        skill_tokens = _keywords(f"{name} {description}")
        if is_explicit or task_tokens.intersection(skill_tokens):
            matches.append(
                SkillSummary(
                    name=name,
                    description=description,
                    path=skill_md.resolve(),
                    explicit=is_explicit,
                )
            )

    return sorted(matches, key=lambda skill: skill.name)


def infer_smoke_script(
    task: TaskSpec,
    repo_root: str | Path,
    *,
    require_exists: bool = True,
) -> Path:
    root = Path(repo_root).resolve()
    exact_candidates: list[Path] = []
    for allowed in task.allowed_paths:
        normalized = allowed.replace("\\", "/")
        if _has_glob(normalized):
            continue
        if normalized.startswith("agent-docs/smoke-tests/") and normalized.endswith(".sh"):
            exact_candidates.append(root / normalized)

    if len(exact_candidates) > 1:
        raise AmbiguousSmokeScript(
            "Multiple exact smoke scripts in allowed_paths: "
            + ", ".join(str(path) for path in exact_candidates)
        )
    if exact_candidates:
        candidate = exact_candidates[0]
        if not require_exists or candidate.exists():
            return candidate
        raise MissingSmokeScript(f"Expected smoke script does not exist: {candidate}")

    stem_candidate = root / "agent-docs" / "smoke-tests" / f"{task.path.stem}.sh"
    if not require_exists or stem_candidate.exists():
        return stem_candidate

    raise MissingSmokeScript(
        f"Could not infer smoke script for {task.path.name}; add an exact "
        "agent-docs/smoke-tests/<task>.sh path to allowed_paths or create "
        f"{stem_candidate.relative_to(root)}"
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
    return _run_subprocess(command, cwd, label=command, timeout_seconds=timeout_seconds, shell=True)


def prepare_run(task: TaskSpec, repo_root: str | Path, prepare_only: bool) -> RunContext:
    root = Path(repo_root).resolve()
    run_id = _new_run_id()
    run_dir = root / "agent-docs" / "runs" / task.id / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    smoke_script = infer_smoke_script(task, root, require_exists=False)
    skills = discover_skills(root, task)
    context = RunContext(
        task=task,
        run_id=run_id,
        run_dir=run_dir,
        smoke_script=smoke_script,
        skills=skills,
        prepare_only=prepare_only,
    )

    (run_dir / "maker-prompt.md").write_text(_maker_prompt(context), encoding="utf-8")
    (run_dir / "verifier-prompt.md").write_text(_verifier_prompt(context), encoding="utf-8")
    (run_dir / "reflection-prompt.md").write_text(_reflection_prompt(context), encoding="utf-8")
    _write_run_json(
        context,
        {
            "status": "prepared",
            "baseline_changed_files": collect_changed_files(root),
            "verification": {
                "smoke_script": str(smoke_script),
                "test_commands": task.test_commands,
                "test_commands_missing": "test_commands" not in task.frontmatter,
                "runner_owned": True,
            },
            "agents": _agent_manifest(context),
            "skills": [_skill_json(skill) for skill in skills],
        },
    )
    return context


def verify_task(
    task: TaskSpec,
    repo_root: str | Path,
    run_dir: str | Path,
    *,
    api_key_env: str | None = None,
    start_server: bool = True,
    skip_smoke: bool = False,
    command_timeout_seconds: int = 1_800,
) -> VerificationResult:
    root = Path(repo_root).resolve()
    output_dir = Path(run_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    project = load_project_config(root)

    gates: list[GateResult] = []
    commands: list[CommandResult] = []

    # Run artifacts (prompts, gate results, service logs) are written by the
    # runner itself, so they are never in-scope maker changes.
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

    test_commands_defined = "test_commands" in task.frontmatter
    gates.append(
        GateResult(
            name="test_commands_defined",
            passed=test_commands_defined,
            details={} if test_commands_defined else {"error": "task frontmatter missing test_commands"},
        )
    )

    test_results: list[CommandResult] = []
    for command in task.test_commands:
        result = run_command(command, root, timeout_seconds=command_timeout_seconds)
        test_results.append(result)
        commands.append(result)
    _write_json(output_dir / "unit-tests.json", [result.to_json() for result in test_results])
    gates.append(
        GateResult(
            name="required_tests",
            passed=all(result.exit_code == 0 for result in test_results),
            details={"count": len(test_results)},
        )
    )

    try:
        smoke_script = infer_smoke_script(task, root)
        gates.append(
            GateResult(
                name="smoke_script_exists",
                passed=True,
                details={"path": str(smoke_script)},
            )
        )
    except RunnerError as exc:
        smoke_script = None
        gates.append(
            GateResult(
                name="smoke_script_exists",
                passed=False,
                details={"error": str(exc)},
            )
        )

    smoke_result: CommandResult | None = None
    if skip_smoke:
        passed = False
        details: dict[str, Any] = {"skipped": True, "reason": "--skip-smoke cannot produce acceptance"}
    elif smoke_script is None:
        passed = False
        details = {"skipped": True, "reason": "missing smoke script"}
    else:
        smoke_result = _run_smoke_gate(
            smoke_script,
            root,
            output_dir,
            project=project,
            api_key_env=api_key_env or project.api_key_env,
            start_server=start_server,
            command_timeout_seconds=command_timeout_seconds,
        )
        commands.append(smoke_result)
        passed = smoke_result.exit_code == 0
        details = {"command": smoke_result.command, "exit_code": smoke_result.exit_code}
    gates.append(GateResult(name="smoke_execution", passed=passed, details=details))
    _write_json(output_dir / "smoke.json", smoke_result.to_json() if smoke_result else None)

    status = "needs_verifier" if all(gate.passed for gate in gates) else "failed"
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
    parser = argparse.ArgumentParser(description="Prepare or verify an agent-docs task loop run.")
    parser.add_argument("task", help="Path to agent-docs/tasks/<task>.md")
    parser.add_argument("--repo-root", default=".", help="Repository root; defaults to cwd")
    parser.add_argument("--prepare-run", action="store_true", help="Generate prompts/artifacts without verification")
    parser.add_argument("--verify-only", action="store_true", help="Run verification gates against current worktree")
    parser.add_argument("--run-dir", help="Existing run artifact directory for --verify-only")
    parser.add_argument("--api-key-env", default=None, help="Env var containing API key for smoke scripts; overrides loop.yaml api_key_env")
    parser.add_argument("--no-start-server", action="store_true", help="Run smoke against an already-running server")
    parser.add_argument("--skip-smoke", action="store_true", help="Diagnostic only; prevents acceptance")
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
                api_key_env=args.api_key_env,
                start_server=not args.no_start_server,
                skip_smoke=args.skip_smoke,
                command_timeout_seconds=args.timeout_seconds,
            )
            print(json.dumps(result.to_json(), indent=2))
            return 0 if result.status == "needs_verifier" else 1

        prepare_only = args.prepare_run
        context = prepare_run(task, root, prepare_only=prepare_only)
        print(f"run_dir={context.run_dir}")
        print(f"maker_prompt={context.run_dir / 'maker-prompt.md'}")
        print(f"verifier_prompt={context.run_dir / 'verifier-prompt.md'}")
        if not prepare_only:
            print("prompt backend prepared; hand maker-prompt.md to a maker agent, then rerun with --verify-only")
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


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise FrontmatterError(f"Expected list, got {type(value).__name__}")
    return [str(item) for item in value]


def _keywords(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) >= 4}


def _has_glob(path: str) -> bool:
    return any(char in path for char in "*?[")


def _path_allowed(relative_changed: str, absolute_changed: str, allowed_paths: list[str], repo_root: Path) -> bool:
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


def _maker_prompt(context: RunContext) -> str:
    task = context.task
    return f"""# Maker Task: {task.id} {task.title}

You are the maker agent for this local agent-docs loop run.

## Non-negotiable workflow

1. Read the task doc and every `read_first` file.
2. Stay within `allowed_paths`.
3. Follow red-green TDD: write a failing test, run it red, implement, run it green.
4. Write or update the mandatory smoke script.
5. Do not claim final acceptance. The runner owns final verification commands.

## Task doc

{task.path}

## Read first

{_bullet(task.read_first)}

## Allowed paths

{_bullet(task.allowed_paths)}

## Test commands the runner will execute

{_test_command_bullets(task)}

## Smoke script the runner will execute

{context.smoke_script}

## Role skill

{_role_skill_bullet(context, "agent-docs-maker")}

## Selected repo-local skills

{_skill_bullets(context.skills)}

## Required maker output

- Changed files.
- Red test command and failure reason.
- Green test commands and result summaries.
- Smoke script path.
- Any unresolved risks for the verifier.
"""


def _verifier_prompt(context: RunContext) -> str:
    task = context.task
    return f"""# Verifier Task: {task.id} {task.title}

You are the independent verifier for this local agent-docs loop run.

Use fresh judgment. Do not trust the maker summary. Review the task doc, diff,
unit-test artifact, smoke artifact, service logs, and handoff notes.

Return exactly one verdict:

- `accepted`
- `needs_work`
- `blocked`

## Acceptance gates owned by the runner

- Changed files must stay within `allowed_paths`.
- Every task `test_commands` command must pass.
- The mandatory smoke script must exist and pass.
- If blocked, Handoff must include commands run, failures seen, and next hypothesis.

## Task doc

{task.path}

## Allowed paths

{_bullet(task.allowed_paths)}

## Test commands

{_test_command_bullets(task)}

## Smoke script

{context.smoke_script}

## Role skill

{_role_skill_bullet(context, "agent-docs-verifier")}

## Selected repo-local skills

{_skill_bullets(context.skills)}
"""


def _reflection_prompt(context: RunContext) -> str:
    return f"""# Reflection Task: {context.task.id} {context.task.title}

Run this only after all runner-owned gates pass and the verifier returns
`accepted`.

Decide whether this accepted run should create or update a repo-local skill under
`agent-docs/skills/<skill-name>/SKILL.md`.

## Role skill

{_role_skill_bullet(context, "agent-docs-reflection")}

Create/update a skill only when the run captured repeated or hard workflow
knowledge. Keep SKILL.md concise and move long details to `references/`.
If no skill is warranted, write a one-sentence reason for `run.json`.
"""


def _write_run_json(context: RunContext, extra: dict[str, Any]) -> None:
    payload = {
        "run_id": context.run_id,
        "task_id": context.task.id,
        "task_path": str(context.task.path),
        "created_at": datetime.now(UTC).isoformat(),
        "prepare_only": context.prepare_only,
        "loop": dataclasses.asdict(context.task.loop),
        **extra,
    }
    _write_json(context.run_dir / "run.json", payload)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _skill_json(skill: SkillSummary) -> dict[str, Any]:
    return {
        "name": skill.name,
        "description": skill.description,
        "path": str(skill.path),
        "explicit": skill.explicit,
    }


def _agent_manifest(context: RunContext) -> dict[str, dict[str, Any]]:
    selected_skills = [_skill_json(skill) for skill in context.skills]
    return {
        "maker": _agent_json(
            context,
            role_skill_name="agent-docs-maker",
            prompt_filename="maker-prompt.md",
            selected_skills=selected_skills,
        ),
        "verifier": _agent_json(
            context,
            role_skill_name="agent-docs-verifier",
            prompt_filename="verifier-prompt.md",
            selected_skills=selected_skills,
        ),
        "reflection": _agent_json(
            context,
            role_skill_name="agent-docs-reflection",
            prompt_filename="reflection-prompt.md",
            selected_skills=[],
        ),
    }


def _agent_json(
    context: RunContext,
    *,
    role_skill_name: str,
    prompt_filename: str,
    selected_skills: list[dict[str, Any]],
) -> dict[str, Any]:
    role_skill = _role_skill_path(context, role_skill_name)
    return {
        "prompt": str(context.run_dir / prompt_filename),
        "role_skill": str(role_skill) if role_skill else None,
        "role_skill_name": role_skill_name,
        "selected_skills": selected_skills,
    }


def _skill_bullets(skills: list[SkillSummary]) -> str:
    if not skills:
        return "- None"
    return "\n".join(f"- `{skill.name}`: {skill.path} — {skill.description}" for skill in skills)


def _role_skill_path(context: RunContext, skill_name: str) -> Path | None:
    candidates = [
        context.task.repo_root / "agent-docs" / "skills" / skill_name / "SKILL.md",
        CORE_SKILLS_DIR / skill_name / "SKILL.md",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _role_skill_bullet(context: RunContext, skill_name: str) -> str:
    path = _role_skill_path(context, skill_name)
    if path:
        return f"- Read `{path}` before doing this role."
    return f"- `{skill_name}` not found in repo-local or agent-core skills."


def _bullet(items: list[str]) -> str:
    if not items:
        return "- None"
    return "\n".join(f"- `{item}`" for item in items)


def _test_command_bullets(task: TaskSpec) -> str:
    if "test_commands" not in task.frontmatter:
        return (
            "- Missing from task frontmatter. Derive the commands, add "
            "`test_commands` to the task doc, and run them before handoff."
        )
    return _bullet(task.test_commands)


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


def _run_smoke_gate(
    smoke_script: Path,
    repo_root: Path,
    run_dir: Path,
    *,
    project: ProjectConfig,
    api_key_env: str | None,
    start_server: bool,
    command_timeout_seconds: int,
) -> CommandResult:
    command = ["bash", str(smoke_script)]
    label = f"bash {shlex.quote(str(smoke_script))}"
    if api_key_env:
        label = f"{label} <${api_key_env}>"
        api_key = os.environ.get(api_key_env)
        if not api_key:
            return CommandResult(
                command=label,
                cwd=str(repo_root),
                exit_code=2,
                stdout="",
                stderr=f"Missing API key env var: {api_key_env}",
                duration_seconds=0,
            )
        command.append(api_key)

    started: list[tuple[ServiceConfig, subprocess.Popen[str]]] = []
    try:
        if start_server:
            _start_services(project.services, repo_root, run_dir, started)
        return _run_subprocess(
            command,
            repo_root,
            label=label,
            timeout_seconds=command_timeout_seconds,
        )
    except RunnerError as exc:
        return CommandResult(
            command=label,
            cwd=str(repo_root),
            exit_code=1,
            stdout="",
            stderr=str(exc),
            duration_seconds=0,
        )
    finally:
        for _, process in reversed(started):
            _stop_process(process)


def _start_services(
    services: list[ServiceConfig],
    repo_root: Path,
    run_dir: Path,
    started: list[tuple[ServiceConfig, subprocess.Popen[str]]],
) -> None:
    for service in services:
        if service.health_url and _url_ok(
            service.health_url, headers=service.health_headers, timeout_seconds=5
        ):
            continue
        cwd = repo_root / service.cwd if service.cwd else repo_root
        if service.background:
            started.append((service, _start_background_service(service, cwd, run_dir)))
        else:
            result = _run_subprocess(
                service.command,
                cwd,
                label=service.command,
                timeout_seconds=service.startup_timeout_seconds,
                shell=True,
                env=_service_env(service),
            )
            _write_json(run_dir / f"{service.name}-start.json", result.to_json())
            if result.exit_code != 0:
                raise RunnerError(f"service `{service.name}` failed to start: {service.command}")
        if service.health_url:
            _wait_for_url(
                service.health_url,
                timeout_seconds=service.startup_timeout_seconds,
                headers=service.health_headers,
            )


def _service_env(service: ServiceConfig) -> dict[str, str]:
    env = os.environ.copy()
    for key, value in service.env.items():
        env.setdefault(key, value)
    return env


def _start_background_service(
    service: ServiceConfig, cwd: Path, run_dir: Path
) -> subprocess.Popen[str]:
    log_file = (run_dir / f"{service.name}.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        service.command,
        shell=True,
        cwd=str(cwd),
        env=_service_env(service),
        text=True,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_file.close()
    return process


def _run_subprocess(
    args: list[str] | str,
    cwd: str | Path,
    *,
    label: str,
    timeout_seconds: int,
    shell: bool = False,
    env: dict[str, str] | None = None,
) -> CommandResult:
    start = time.monotonic()
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd),
            shell=shell,
            env=env,
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


def _url_ok(url: str, *, headers: dict[str, str] | None = None, timeout_seconds: int = 3) -> bool:
    request = Request(url, headers=headers or {}, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return 200 <= response.status < 500
    except URLError:
        return False


def _wait_for_url(url: str, timeout_seconds: int, *, headers: dict[str, str] | None = None) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _url_ok(url, headers=headers):
            return
        time.sleep(2)
    raise RunnerError(f"Timed out waiting for {url}")


def _stop_process(process: subprocess.Popen[str]) -> None:
    # Background services run in their own session; signal the whole group so
    # shell-spawned children die with their parent.
    if process.poll() is not None:
        return
    if not _signal_group(process, signal.SIGTERM):
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if _signal_group(process, signal.SIGKILL):
            process.wait(timeout=10)


def _signal_group(process: subprocess.Popen[str], signum: int) -> bool:
    try:
        os.killpg(os.getpgid(process.pid), signum)
        return True
    except ProcessLookupError:
        return False


if __name__ == "__main__":
    sys.exit(main())
