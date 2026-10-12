# ABOUTME: Tests for the simplified agent-docs runner.
# ABOUTME: Covers task parsing, diff guardrails, command execution, and run artifacts.

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from loop.runner import (  # noqa: E402
    CommandResult,
    FrontmatterError,
    RunnerError,
    check_allowed_paths,
    collect_changed_files,
    create_task,
    discover_resume,
    load_task,
    main,
    prepare_run,
    record_review,
    run_command,
    verify_task,
)


@pytest.fixture(autouse=True)
def python_command_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"])


def write_task(repo_root: Path, body: str) -> Path:
    task_path = repo_root / "agent-docs" / "tasks" / "PR-99-demo.md"
    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(body, encoding="utf-8")
    if not (repo_root / ".git").exists():
        init_repo(repo_root)
    return task_path


def write_demo_task(
    repo_root: Path,
    *,
    allowed_paths: list[str] | None = None,
    test_commands: list[str] | None = None,
    smoke_command: str | None = None,
    coordination: str = "",
) -> Path:
    allowed = allowed_paths or ["src/**"]
    commands = test_commands if test_commands is not None else ['python -c "print(\'ok\')"']
    smoke = f"smoke_command: {smoke_command}\n" if smoke_command else ""
    acceptance = (
        "acceptance:\n  - condition: The declared regression check succeeds\n"
        f"    command: {json.dumps(commands[0])}\n" if commands else ""
    )
    return write_task(
        repo_root,
        f"""---
id: PR-99
title: Demo Task
read_first:
  - README.md
allowed_paths:
{yaml_list(allowed)}
test_commands:
{yaml_list(commands)}
{acceptance}
{coordination}
{smoke}---

# PR-99
""",
    )


def write_named_demo_task(repo_root: Path, task_id: str) -> Path:
    task_path = repo_root / "agent-docs" / "tasks" / f"{task_id}-demo.md"
    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(
        f"""---
id: {task_id}
title: Demo {task_id}
allowed_paths:
  - src/**
test_commands:
  - python -c "print('ok')"
acceptance:
  - condition: The declared regression check succeeds
    command: python -c "print('ok')"
---

# {task_id}
""",
        encoding="utf-8",
    )
    if not (repo_root / ".git").exists():
        init_repo(repo_root)
    return task_path


def set_run_created_at(run_dir: Path, created_at: str) -> None:
    run_json = run_dir / "run.json"
    payload = json.loads(run_json.read_text(encoding="utf-8"))
    payload["created_at"] = created_at
    run_json.write_text(json.dumps(payload), encoding="utf-8")


def write_verification(run_dir: Path, status: str) -> None:
    metadata = json.loads((run_dir / "run.json").read_text())
    root = Path(metadata["repo_root"])
    task = load_task(metadata["task_path"], root)
    if status == "failed":
        (root / "forbidden.txt").write_text("trigger actual scope failure", encoding="utf-8")
    assert verify_task(task, root, run_dir).status == status


def yaml_list(items: list[str]) -> str:
    if not items:
        return "  []"
    return "\n".join(f"  - {item}" for item in items)


def init_repo(repo_root: Path) -> None:
    for command in (
        ["git", "init", "-q"],
        ["git", "add", "-A"],
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-qm", "init"],
    ):
        subprocess.run(command, cwd=repo_root, check=True)


def install_skills_script() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "install_skills.py"


def test_load_task_parses_minimal_frontmatter(tmp_path: Path) -> None:
    task_path = write_demo_task(
        tmp_path,
        allowed_paths=["src/api/**", "tests/**"],
        smoke_command='python -c "print(\'smoke\')"',
    )

    task = load_task(task_path, tmp_path)

    assert task.id == "PR-99"
    assert task.title == "Demo Task"
    assert task.read_first == ["README.md"]
    assert task.allowed_paths == ["src/api/**", "tests/**"]
    assert task.test_commands == ['python -c "print(\'ok\')"']
    assert task.smoke_command == 'python -c "print(\'smoke\')"'
    assert task.coordination.mode == "solo"


def test_load_task_parses_coordination_profiles(tmp_path: Path) -> None:
    task_path = write_demo_task(
        tmp_path,
        coordination="""coordination:
  mode: delegated
  maker:
    characterization: Staff Python engineer with deep CLI runner experience.
  reviewer:
    characterization: Principal test-infrastructure reviewer focused on gates.
""",
    )

    task = load_task(task_path, tmp_path)

    assert task.coordination.mode == "delegated"
    assert (
        task.coordination.maker_characterization
        == "Staff Python engineer with deep CLI runner experience."
    )
    assert (
        task.coordination.reviewer_characterization
        == "Principal test-infrastructure reviewer focused on gates."
    )


def test_load_task_requires_reviewer_characterization_for_review(tmp_path: Path) -> None:
    task_path = write_demo_task(
        tmp_path,
        coordination="""coordination:
  mode: review
""",
    )

    with pytest.raises(FrontmatterError, match="coordination.reviewer.characterization"):
        load_task(task_path, tmp_path)


def test_load_task_rejects_non_string_coordination_mode(tmp_path: Path) -> None:
    task_path = write_demo_task(
        tmp_path,
        coordination="""coordination:
  mode: 7
""",
    )

    with pytest.raises(FrontmatterError, match="coordination.mode must be a string"):
        load_task(task_path, tmp_path)


def test_load_task_rejects_non_string_role_characterization(tmp_path: Path) -> None:
    task_path = write_demo_task(
        tmp_path,
        coordination="""coordination:
  mode: review
  reviewer:
    characterization:
      - not
      - a
      - string
""",
    )

    with pytest.raises(
        FrontmatterError,
        match="coordination.reviewer.characterization must be a string",
    ):
        load_task(task_path, tmp_path)


def test_load_task_requires_test_commands(tmp_path: Path) -> None:
    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Demo Task
allowed_paths:
  - src/**
---

# PR-99
""",
    )

    with pytest.raises(FrontmatterError, match="test_commands"):
        load_task(task_path, tmp_path)


def test_check_allowed_paths_supports_relative_and_absolute_patterns(tmp_path: Path) -> None:
    sibling = tmp_path.parent / "web" / "apps" / "creator" / "route.ts"
    allowed = [
        "src/api/**",
        str(tmp_path.parent / "web" / "apps" / "creator" / "**"),
    ]

    violations = check_allowed_paths(
        [
            "src/api/search.py",
            str(sibling),
            "src/legacy/videos.py",
        ],
        allowed,
        tmp_path,
    )

    assert violations == ["src/legacy/videos.py"]


def test_collect_changed_files_includes_deleted_tracked_files(tmp_path: Path) -> None:
    deleted = tmp_path / "src" / "outside_allowed.py"
    deleted.parent.mkdir()
    deleted.write_text("old\n", encoding="utf-8")
    init_repo(tmp_path)

    deleted.unlink()

    assert collect_changed_files(tmp_path) == ["src/outside_allowed.py"]


def test_run_command_records_command_result(tmp_path: Path) -> None:
    result = run_command("python -c \"print('ok')\"", tmp_path, timeout_seconds=10)

    assert isinstance(result, CommandResult)
    assert result.exit_code == 0
    assert result.stdout.strip() == "ok"
    assert result.duration_seconds >= 0


def test_create_task_bootstraps_agent_docs_and_writes_valid_task(tmp_path: Path) -> None:
    task_path = create_task(
        tmp_path,
        task_id="PR-12",
        title="Fix Search Pagination",
        read_first=["README.md"],
        allowed_paths=["src/search/**", "tests/search/**"],
        test_commands=["pytest tests/search/test_pagination.py"],
        coordination_mode="review",
        reviewer_characterization="Principal search reviewer focused on pagination.",
    )

    assert task_path == tmp_path / "agent-docs" / "tasks" / "PR-12-fix-search-pagination.md"
    assert (tmp_path / "agent-docs" / "MEMORY.md").exists()
    assert (tmp_path / "agent-docs" / "skills" / "README.md").exists()

    task = load_task(task_path, tmp_path)
    assert task.id == "PR-12"
    assert task.title == "Fix Search Pagination"
    assert task.allowed_paths == ["src/search/**", "tests/search/**"]
    assert task.coordination.mode == "review"
    assert (
        task.coordination.reviewer_characterization
        == "Principal search reviewer focused on pagination."
    )
    assert "Describe the change" in task_path.read_text(encoding="utf-8")


def test_create_task_refuses_to_overwrite_existing_task(tmp_path: Path) -> None:
    kwargs = {
        "task_id": "PR-12",
        "title": "Fix Search Pagination",
        "read_first": [],
        "allowed_paths": ["src/**"],
        "test_commands": ["pytest"],
    }
    create_task(tmp_path, **kwargs)

    with pytest.raises(RunnerError, match="already exists"):
        create_task(tmp_path, **kwargs)


def test_create_task_validates_required_task_fields(tmp_path: Path) -> None:
    with pytest.raises(FrontmatterError, match="--allowed-path"):
        create_task(
            tmp_path,
            task_id="PR-12",
            title="Fix Search Pagination",
            read_first=[],
            allowed_paths=[],
            test_commands=["pytest"],
        )


def test_main_creates_task_from_cli(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    exit_code = main(
        [
            "--repo-root",
            str(tmp_path),
            "--new-task",
            "PR-12",
            "--title",
            "Fix Search Pagination",
            "--allowed-path",
            "src/search/**",
            "--test-command",
            "pytest tests/search/test_pagination.py",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "task=" in captured.out
    assert (tmp_path / "agent-docs" / "tasks" / "PR-12-fix-search-pagination.md").exists()


def test_install_skills_script_installs_repo_local_skill(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(install_skills_script()),
            "--dest",
            str(tmp_path / "skills"),
            "--claude-dir",
            str(tmp_path / "claude"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    installed = tmp_path / "skills" / "agent-docs-loop" / "SKILL.md"
    assert installed.exists()
    assert "codex:installed: skill:agent-docs-loop" in result.stdout


def test_install_skills_script_skips_existing_skill(tmp_path: Path) -> None:
    destination = tmp_path / "skills"
    subprocess.run(
        [
            sys.executable,
            str(install_skills_script()),
            "--dest",
            str(destination),
            "--claude-dir",
            str(tmp_path / "claude"),
        ],
        check=True,
    )

    result = subprocess.run(
        [
            sys.executable,
            str(install_skills_script()),
            "--dest",
            str(destination),
            "--claude-dir",
            str(tmp_path / "claude"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "codex:skipped-existing: skill:agent-docs-loop" in result.stdout


def test_install_skills_script_force_replaces_existing_skill(tmp_path: Path) -> None:
    destination = tmp_path / "skills"
    skill_dir = destination / "agent-docs-loop"
    skill_dir.mkdir(parents=True)
    (skill_dir / "stale.txt").write_text("stale\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(install_skills_script()),
            "--dest",
            str(destination),
            "--claude-dir",
            str(tmp_path / "claude"),
            "--force",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "codex:replaced: skill:agent-docs-loop" in result.stdout
    assert not (skill_dir / "stale.txt").exists()
    assert (skill_dir / "SKILL.md").exists()


def test_install_skills_script_installs_claude_skill_and_command(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(install_skills_script()),
            "--dest",
            str(tmp_path / "codex-skills"),
            "--claude-dir",
            str(tmp_path / "claude"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    skill = tmp_path / "claude" / "skills" / "agent-docs-loop" / "SKILL.md"
    command = tmp_path / "claude" / "commands" / "agent-docs-loop.md"
    assert skill.exists()
    assert command.exists()
    assert "claude:installed: skill:agent-docs-loop" in result.stdout
    assert "claude:installed: command:agent-docs-loop" in result.stdout
    command_text = command.read_text(encoding="utf-8")
    assert str(skill) in command_text
    assert "Repository Mode" in command_text
    assert "assessment and explanation requests read-only" in command_text


def test_install_skills_script_defaults_to_all_agents_with_temp_dirs(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(install_skills_script()),
            "--dest",
            str(tmp_path / "codex-skills"),
            "--claude-dir",
            str(tmp_path / "claude"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert (tmp_path / "codex-skills" / "agent-docs-loop" / "SKILL.md").exists()
    assert (tmp_path / "claude" / "skills" / "agent-docs-loop" / "SKILL.md").exists()
    assert "codex:installed: skill:agent-docs-loop" in result.stdout
    assert "claude:installed: command:agent-docs-loop" in result.stdout


def test_prepare_run_writes_single_prompt_and_run_json(tmp_path: Path) -> None:
    task_path = write_demo_task(tmp_path, smoke_command='python -c "print(\'smoke\')"')
    task = load_task(task_path, tmp_path)

    run = prepare_run(task, tmp_path)

    assert (run.run_dir / "prompt.md").exists()
    assert (run.run_dir / "handoff.md").exists()
    assert (run.run_dir / "subagents" / "README.md").exists()
    run_json = json.loads((run.run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_json["task_id"] == "PR-99"
    assert run_json["status"] == "prepared"
    assert run_json["handoff"] == str(run.run_dir / "handoff.md")
    assert run_json["subagents_dir"] == str(run.run_dir / "subagents")
    assert run_json["coordination"]["mode"] == "solo"
    assert run_json["verification"]["test_commands"] == task.test_commands
    assert run_json["verification"]["smoke_command"] == task.smoke_command
    prompt = (run.run_dir / "prompt.md").read_text(encoding="utf-8")
    assert "handoff.md" in prompt
    assert "subagents" in prompt
    assert "Mode: `solo`" in prompt
    assert "no external CLI or model" in prompt
    assert "--record-review" in prompt


def test_prepare_run_writes_delegated_role_characterizations(tmp_path: Path) -> None:
    task_path = write_demo_task(
        tmp_path,
        coordination="""coordination:
  mode: delegated
  maker:
    characterization: Staff Python engineer with deep CLI runner experience.
  reviewer:
    characterization: Principal test-infrastructure reviewer focused on gates.
""",
    )
    task = load_task(task_path, tmp_path)

    run = prepare_run(task, tmp_path)

    prompt = (run.run_dir / "prompt.md").read_text(encoding="utf-8")
    subagents_readme = (run.run_dir / "subagents" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "Mode: `delegated`" in prompt
    assert "`subagents/maker.md`" in prompt
    assert "Staff Python engineer with deep CLI runner experience." in subagents_readme
    assert "Principal test-infrastructure reviewer focused on gates." in subagents_readme


def test_discover_resume_returns_intake_when_no_valid_runs(tmp_path: Path) -> None:
    result = discover_resume(tmp_path)

    assert result.action == "intake_required"
    assert result.repo_root == str(tmp_path)
    assert result.task_path is None
    assert result.run_dir is None
    assert result.verification_status is None
    assert result.warnings == []


def test_discover_resume_prefers_newest_unfinished_run_over_completed_runs(
    tmp_path: Path,
) -> None:
    unfinished_task = load_task(write_named_demo_task(tmp_path, "PR-10"), tmp_path)
    unfinished = prepare_run(unfinished_task, tmp_path)
    set_run_created_at(unfinished.run_dir, "2026-01-01T00:00:00+00:00")

    newer_unfinished_task = load_task(write_named_demo_task(tmp_path, "PR-20"), tmp_path)
    newer_unfinished = prepare_run(newer_unfinished_task, tmp_path)
    set_run_created_at(newer_unfinished.run_dir, "2026-01-02T00:00:00+00:00")

    completed_task = load_task(write_named_demo_task(tmp_path, "PR-30"), tmp_path)
    completed = prepare_run(completed_task, tmp_path)
    set_run_created_at(completed.run_dir, "2026-01-03T00:00:00+00:00")
    write_verification(completed.run_dir, "passed")

    result = discover_resume(tmp_path)

    assert result.action == "resume"
    assert result.task_id == "PR-20"
    assert result.run_dir == str(newer_unfinished.run_dir)
    assert result.prompt == str(newer_unfinished.run_dir / "prompt.md")
    assert result.handoff == str(newer_unfinished.run_dir / "handoff.md")
    assert result.verification == str(newer_unfinished.run_dir / "verification.json")
    assert result.verification_status == "missing"


def test_discover_resume_reports_failed_verification_as_resumable(tmp_path: Path) -> None:
    task = load_task(write_named_demo_task(tmp_path, "PR-40"), tmp_path)
    run = prepare_run(task, tmp_path)
    write_verification(run.run_dir, "failed")

    result = discover_resume(tmp_path)

    assert result.action == "resume"
    assert result.run_dir == str(run.run_dir)
    assert result.verification_status == "failed"


def test_discover_resume_returns_newest_completed_run_as_context(tmp_path: Path) -> None:
    older_task = load_task(write_named_demo_task(tmp_path, "PR-50"), tmp_path)
    older = prepare_run(older_task, tmp_path)
    set_run_created_at(older.run_dir, "2026-01-01T00:00:00+00:00")
    write_verification(older.run_dir, "passed")

    newer_task = load_task(write_named_demo_task(tmp_path, "PR-60"), tmp_path)
    newer = prepare_run(newer_task, tmp_path)
    set_run_created_at(newer.run_dir, "2026-01-02T00:00:00+00:00")
    write_verification(newer.run_dir, "passed")

    result = discover_resume(tmp_path)

    assert result.action == "completed_context"
    assert result.task_id == "PR-60"
    assert result.run_dir == str(newer.run_dir)
    assert result.verification_status == "passed"


def test_discover_resume_skips_malformed_metadata_and_missing_artifacts(
    tmp_path: Path,
) -> None:
    malformed = tmp_path / "agent-docs" / "runs" / "BAD" / "bad-run"
    malformed.mkdir(parents=True)
    (malformed / "run.json").write_text("{not json", encoding="utf-8")

    task = load_task(write_named_demo_task(tmp_path, "PR-70"), tmp_path)
    missing_artifacts = prepare_run(task, tmp_path)
    (missing_artifacts.run_dir / "prompt.md").unlink()

    result = discover_resume(tmp_path)

    assert result.action == "intake_required"
    assert len(result.warnings) == 2
    assert any("malformed run metadata" in warning for warning in result.warnings)
    assert any("missing artifacts" in warning for warning in result.warnings)


def test_discover_resume_skips_task_paths_outside_repository(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    task = load_task(write_named_demo_task(repo_root, "PR-80"), repo_root)
    run = prepare_run(task, repo_root)
    outside_task = tmp_path / "outside-task.md"
    outside_task.write_text("outside\n", encoding="utf-8")
    run_json = run.run_dir / "run.json"
    payload = json.loads(run_json.read_text(encoding="utf-8"))
    payload["task_path"] = str(outside_task)
    run_json.write_text(json.dumps(payload), encoding="utf-8")

    result = discover_resume(repo_root)

    assert result.action == "intake_required"
    assert any("unsafe or missing task path" in warning for warning in result.warnings)


def test_discover_resume_rejects_runs_directory_outside_repository(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "agent-docs").mkdir(parents=True)
    outside_runs = tmp_path / "outside-runs"
    outside_runs.mkdir()
    (repo_root / "agent-docs" / "runs").symlink_to(outside_runs, target_is_directory=True)

    result = discover_resume(repo_root)

    assert result.action == "intake_required"
    assert result.warnings == [
        "Skipped agent-docs/runs because it escapes the repository"
    ]


def test_main_discovers_resume_for_repo_outside_current_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caller = tmp_path / "caller"
    caller.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    task = load_task(write_named_demo_task(target, "PR-90"), target)
    run = prepare_run(task, target)
    monkeypatch.chdir(caller)

    exit_code = main(["--repo-root", str(target), "--resume"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["action"] == "resume"
    assert output["repo_root"] == str(target)
    assert output["run_dir"] == str(run.run_dir)


def test_verify_task_passes_tests_and_skips_missing_smoke(tmp_path: Path) -> None:
    task_path = write_demo_task(tmp_path)
    task = load_task(task_path, tmp_path)

    run = prepare_run(task, tmp_path)
    result = verify_task(task, tmp_path, run.run_dir)

    assert result.status == "passed"
    assert [gate.name for gate in result.gates] == [
        "diff_scope",
        "coordination",
        "tests",
        "smoke",
        "snapshot_stability",
        "acceptance",
    ]
    assert next(gate for gate in result.gates if gate.name == "coordination").passed
    assert next(gate for gate in result.gates if gate.name == "smoke").details["skipped"] is True
    assert (run.run_dir / "tests.json").exists()
    assert (run.run_dir / "coordination.json").exists()
    assert (run.run_dir / "verification.json").exists()


def test_verify_task_fails_review_coordination_without_reviewer_artifact(
    tmp_path: Path,
) -> None:
    task_path = write_demo_task(
        tmp_path,
        coordination="""coordination:
  mode: review
  reviewer:
    characterization: Principal Python reviewer focused on runner gates.
""",
    )
    task = load_task(task_path, tmp_path)

    result = verify_task(task, tmp_path, prepare_run(task, tmp_path).run_dir)

    coordination_gate = next(gate for gate in result.gates if gate.name == "coordination")
    assert result.status == "failed"
    assert not coordination_gate.passed
    assert coordination_gate.details["missing_artifacts"] == ["subagents/reviewer.md"]


def test_verify_task_fails_review_coordination_without_approval(tmp_path: Path) -> None:
    task_path = write_demo_task(
        tmp_path,
        coordination="""coordination:
  mode: review
  reviewer:
    characterization: Principal Python reviewer focused on runner gates.
""",
    )
    task = load_task(task_path, tmp_path)
    run_dir = prepare_run(task, tmp_path).run_dir
    subagents = run_dir / "subagents"
    subagents.mkdir(parents=True, exist_ok=True)
    (subagents / "reviewer.md").write_text("Verdict: changes_requested\n", encoding="utf-8")
    task = load_task(task_path, tmp_path)

    result = verify_task(task, tmp_path, run_dir)

    coordination_gate = next(gate for gate in result.gates if gate.name == "coordination")
    assert result.status == "failed"
    assert not coordination_gate.passed
    assert coordination_gate.details["reviewer_verdict"] == "changes_requested"
    assert coordination_gate.details["error"] == "reviewer verdict must be approve"


def test_verify_task_uses_last_reviewer_verdict(tmp_path: Path) -> None:
    task_path = write_demo_task(
        tmp_path,
        coordination="""coordination:
  mode: review
  reviewer:
    characterization: Principal Python reviewer focused on runner gates.
""",
    )
    task = load_task(task_path, tmp_path)
    run_dir = prepare_run(task, tmp_path).run_dir
    subagents = run_dir / "subagents"
    subagents.mkdir(parents=True, exist_ok=True)
    (subagents / "reviewer.md").write_text(
        "Verdict: approve\nVerdict: changes_requested\n",
        encoding="utf-8",
    )
    task = load_task(task_path, tmp_path)

    result = verify_task(task, tmp_path, run_dir)

    coordination_gate = next(gate for gate in result.gates if gate.name == "coordination")
    assert result.status == "failed"
    assert not coordination_gate.passed
    assert coordination_gate.details["reviewer_verdict"] == "changes_requested"


def test_verify_task_fails_when_required_artifact_is_directory(tmp_path: Path) -> None:
    task_path = write_demo_task(
        tmp_path,
        coordination="""coordination:
  mode: review
  reviewer:
    characterization: Principal Python reviewer focused on runner gates.
""",
    )
    task = load_task(task_path, tmp_path)
    run_dir = prepare_run(task, tmp_path).run_dir
    (run_dir / "subagents" / "reviewer.md").mkdir(parents=True)
    task = load_task(task_path, tmp_path)

    result = verify_task(task, tmp_path, run_dir)

    coordination_gate = next(gate for gate in result.gates if gate.name == "coordination")
    assert result.status == "failed"
    assert coordination_gate.details["invalid_artifacts"] == ["subagents/reviewer.md"]
    assert (
        coordination_gate.details["invalid_artifact_errors"]["subagents/reviewer.md"]
        == "not a file"
    )


def test_verify_task_passes_review_coordination_with_approval(tmp_path: Path) -> None:
    task_path = write_demo_task(
        tmp_path,
        coordination="""coordination:
  mode: review
  reviewer:
    characterization: Principal Python reviewer focused on runner gates.
""",
    )
    task = load_task(task_path, tmp_path)
    run_dir = prepare_run(task, tmp_path).run_dir
    subagents = run_dir / "subagents"
    subagents.mkdir(parents=True, exist_ok=True)
    (subagents / "reviewer.md").write_text("Verdict: approve\n", encoding="utf-8")
    task = load_task(task_path, tmp_path)

    record_review(task, tmp_path, run_dir)
    result = verify_task(task, tmp_path, run_dir)

    coordination_gate = next(gate for gate in result.gates if gate.name == "coordination")
    assert result.status == "passed"
    assert coordination_gate.passed
    assert coordination_gate.details["reviewer_approved"] is True


def test_verify_task_fails_delegated_coordination_without_maker_artifact(
    tmp_path: Path,
) -> None:
    task_path = write_demo_task(
        tmp_path,
        coordination="""coordination:
  mode: delegated
  maker:
    characterization: Staff Python engineer with deep CLI runner experience.
  reviewer:
    characterization: Principal Python reviewer focused on runner gates.
""",
    )
    task = load_task(task_path, tmp_path)
    run_dir = prepare_run(task, tmp_path).run_dir
    subagents = run_dir / "subagents"
    subagents.mkdir(parents=True, exist_ok=True)
    (subagents / "reviewer.md").write_text("Verdict: approve\n", encoding="utf-8")
    task = load_task(task_path, tmp_path)

    result = verify_task(task, tmp_path, run_dir)

    coordination_gate = next(gate for gate in result.gates if gate.name == "coordination")
    assert result.status == "failed"
    assert not coordination_gate.passed
    assert coordination_gate.details["missing_artifacts"] == ["subagents/maker.md"]


def test_verify_task_fails_when_test_commands_are_empty(tmp_path: Path) -> None:
    task_path = write_demo_task(tmp_path, test_commands=[])
    task = load_task(task_path, tmp_path)

    with pytest.raises(FrontmatterError, match="test_commands"):
        prepare_run(task, tmp_path)


def test_verify_task_runs_optional_smoke_command(tmp_path: Path) -> None:
    task_path = write_demo_task(tmp_path, smoke_command='python -c "print(\'smoke\')"')
    task = load_task(task_path, tmp_path)

    run = prepare_run(task, tmp_path)
    result = verify_task(task, tmp_path, run.run_dir)

    smoke_gate = next(gate for gate in result.gates if gate.name == "smoke")
    assert result.status == "passed"
    assert smoke_gate.passed
    assert smoke_gate.details["exit_code"] == 0
    smoke_json = json.loads((run.run_dir / "smoke.json").read_text(encoding="utf-8"))
    assert smoke_json["stdout"].strip() == "smoke"


def test_verify_task_fails_when_optional_smoke_command_fails(tmp_path: Path) -> None:
    task_path = write_demo_task(tmp_path, smoke_command='python -c "raise SystemExit(7)"')
    task = load_task(task_path, tmp_path)

    result = verify_task(task, tmp_path, prepare_run(task, tmp_path).run_dir)

    smoke_gate = next(gate for gate in result.gates if gate.name == "smoke")
    assert result.status == "failed"
    assert not smoke_gate.passed
    assert smoke_gate.details["exit_code"] == 7


def test_verify_task_flags_changed_file_outside_allowed_paths(tmp_path: Path) -> None:
    task_path = write_demo_task(tmp_path, allowed_paths=["src/api/**"])
    outside_allowed = tmp_path / "src" / "legacy" / "videos.py"
    outside_allowed.parent.mkdir(parents=True)
    outside_allowed.write_text("old\n", encoding="utf-8")
    init_repo(tmp_path)

    task = load_task(task_path, tmp_path)
    run = prepare_run(task, tmp_path)
    outside_allowed.write_text("new\n", encoding="utf-8")

    result = verify_task(task, tmp_path, run.run_dir)

    diff_gate = next(gate for gate in result.gates if gate.name == "diff_scope")
    assert result.status == "failed"
    assert diff_gate.details["changed_files"] == ["src/legacy/videos.py"]
    assert diff_gate.details["violations"] == ["src/legacy/videos.py"]


def test_verify_task_ignores_preexisting_dirty_files_from_prepare_baseline(tmp_path: Path) -> None:
    task_path = write_demo_task(tmp_path, allowed_paths=["src/api/**"])
    dirty = tmp_path / "notes.txt"
    dirty.write_text("clean\n", encoding="utf-8")
    init_repo(tmp_path)
    dirty.write_text("dirty before prepare\n", encoding="utf-8")

    task = load_task(task_path, tmp_path)
    run = prepare_run(task, tmp_path)
    result = verify_task(task, tmp_path, run.run_dir)

    diff_gate = next(gate for gate in result.gates if gate.name == "diff_scope")
    assert result.status == "passed"
    assert diff_gate.details["changed_files"] == []


def test_main_reports_runner_errors_without_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Demo Task
allowed_paths: src/**
test_commands:
  - python -c "print('ok')"
---

# PR-99
""",
    )

    exit_code = main([str(task_path), "--repo-root", str(tmp_path), "--prepare-run"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "ERROR:" in captured.err
    assert "allowed_paths must be a list" in captured.err
    assert "Traceback" not in captured.err
