# ABOUTME: Tests for the simplified agent-docs runner.
# ABOUTME: Covers task parsing, diff guardrails, command execution, and run artifacts.

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from loop.runner import (  # noqa: E402
    CommandResult,
    FrontmatterError,
    check_allowed_paths,
    collect_changed_files,
    filter_baseline_changed_files,
    load_task,
    main,
    prepare_run,
    run_command,
    verify_task,
)


def write_task(repo_root: Path, body: str) -> Path:
    task_path = repo_root / "agent-docs" / "tasks" / "PR-99-demo.md"
    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(body, encoding="utf-8")
    return task_path


def write_demo_task(
    repo_root: Path,
    *,
    allowed_paths: list[str] | None = None,
    test_commands: list[str] | None = None,
    smoke_command: str | None = None,
) -> Path:
    allowed = allowed_paths or ["src/**"]
    commands = test_commands if test_commands is not None else ['python -c "print(\'ok\')"']
    smoke = f"smoke_command: {smoke_command}\n" if smoke_command else ""
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
{smoke}---

# PR-99
""",
    )


def yaml_list(items: list[str]) -> str:
    if not items:
        return "  []"
    return "\n".join(f"  - {item}" for item in items)


def init_repo(repo_root: Path) -> None:
    for command in (
        ["git", "init", "-q"],
        ["git", "add", "-A"],
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"],
    ):
        subprocess.run(command, cwd=repo_root, check=True)


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


def test_filter_baseline_changed_files_ignores_preexisting_dirty_files() -> None:
    assert filter_baseline_changed_files(
        ["agent-docs/loop/runner.py", "preexisting.txt"],
        ["preexisting.txt"],
    ) == ["agent-docs/loop/runner.py"]


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
    assert run_json["verification"]["test_commands"] == task.test_commands
    assert run_json["verification"]["smoke_command"] == task.smoke_command
    prompt = (run.run_dir / "prompt.md").read_text(encoding="utf-8")
    assert "handoff.md" in prompt
    assert "subagents" in prompt


def test_verify_task_passes_tests_and_skips_missing_smoke(tmp_path: Path) -> None:
    task_path = write_demo_task(tmp_path)
    task = load_task(task_path, tmp_path)

    result = verify_task(task, tmp_path, tmp_path / "run")

    assert result.status == "passed"
    assert [gate.name for gate in result.gates] == ["diff_scope", "tests", "smoke"]
    assert next(gate for gate in result.gates if gate.name == "smoke").details["skipped"] is True
    assert (tmp_path / "run" / "tests.json").exists()
    assert (tmp_path / "run" / "verification.json").exists()


def test_verify_task_fails_when_test_commands_are_empty(tmp_path: Path) -> None:
    task_path = write_demo_task(tmp_path, test_commands=[])
    task = load_task(task_path, tmp_path)

    result = verify_task(task, tmp_path, tmp_path / "run")

    tests_gate = next(gate for gate in result.gates if gate.name == "tests")
    assert result.status == "failed"
    assert not tests_gate.passed
    assert tests_gate.details["error"] == "test_commands must contain at least one command"


def test_verify_task_runs_optional_smoke_command(tmp_path: Path) -> None:
    task_path = write_demo_task(tmp_path, smoke_command='python -c "print(\'smoke\')"')
    task = load_task(task_path, tmp_path)

    result = verify_task(task, tmp_path, tmp_path / "run")

    smoke_gate = next(gate for gate in result.gates if gate.name == "smoke")
    assert result.status == "passed"
    assert smoke_gate.passed
    assert smoke_gate.details["exit_code"] == 0
    smoke_json = json.loads((tmp_path / "run" / "smoke.json").read_text(encoding="utf-8"))
    assert smoke_json["stdout"].strip() == "smoke"


def test_verify_task_fails_when_optional_smoke_command_fails(tmp_path: Path) -> None:
    task_path = write_demo_task(tmp_path, smoke_command='python -c "raise SystemExit(7)"')
    task = load_task(task_path, tmp_path)

    result = verify_task(task, tmp_path, tmp_path / "run")

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

    outside_allowed.write_text("new\n", encoding="utf-8")

    task = load_task(task_path, tmp_path)
    result = verify_task(task, tmp_path, tmp_path / "run")

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
