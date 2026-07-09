# ABOUTME: Regression tests for the agent-docs local loop runner.
# ABOUTME: Covers task parsing, guardrails, skill discovery, and prepare-run artifacts.

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from loop.runner import (  # noqa: E402
    CORE_SKILLS_DIR,
    DEFAULT_LOOP_CONFIG,
    CommandResult,
    MissingSmokeScript,
    ProjectConfigError,
    check_allowed_paths,
    collect_changed_files,
    discover_skills,
    filter_baseline_changed_files,
    infer_smoke_script,
    load_project_config,
    load_task,
    main,
    prepare_run,
    run_command,
    verify_task,
)


def write_task(repo_root: Path, body: str) -> Path:
    task_path = repo_root / "agent-docs" / "tasks" / "PR-99-demo.md"
    task_path.parent.mkdir(parents=True)
    task_path.write_text(body, encoding="utf-8")
    return task_path


def test_load_task_applies_loop_defaults(tmp_path: Path) -> None:
    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Demo Loop Task
status: todo
depends_on: []
allowed_paths:
  - src/api/**
  - agent-docs/smoke-tests/PR-99-demo.sh
read_first:
  - agent-docs/TESTING.md
test_commands:
  - python -c "print('ok')"
rollback: Revert demo changes.
---

# PR-99
""",
    )

    task = load_task(task_path, tmp_path)

    assert task.id == "PR-99"
    assert task.title == "Demo Loop Task"
    assert task.loop.max_attempts == DEFAULT_LOOP_CONFIG.max_attempts
    assert task.loop.max_no_progress_attempts == DEFAULT_LOOP_CONFIG.max_no_progress_attempts
    assert task.loop.skills == []


def test_load_task_overrides_loop_config(tmp_path: Path) -> None:
    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Demo Loop Task
status: todo
allowed_paths:
  - agent-docs/smoke-tests/PR-99-demo.sh
read_first: []
test_commands: []
rollback: Revert demo changes.
loop:
  max_attempts: 5
  max_no_progress_attempts: 1
  max_wall_minutes: 45
  maker_token_budget: 123
  verifier_token_budget: 456
  reflection_token_budget: 789
  skills:
    - api-task
---

# PR-99
""",
    )

    task = load_task(task_path, tmp_path)

    assert task.loop.max_attempts == 5
    assert task.loop.max_no_progress_attempts == 1
    assert task.loop.max_wall_minutes == 45
    assert task.loop.maker_token_budget == 123
    assert task.loop.verifier_token_budget == 456
    assert task.loop.reflection_token_budget == 789
    assert task.loop.skills == ["api-task"]


def test_load_task_allows_missing_test_commands_for_preparation(tmp_path: Path) -> None:
    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Demo Loop Task
status: todo
allowed_paths:
  - agent-docs/smoke-tests/PR-99-demo.sh
read_first: []
rollback: Revert demo changes.
---

# PR-99
""",
    )

    task = load_task(task_path, tmp_path)

    assert task.test_commands == []
    assert "test_commands" not in task.frontmatter


def test_infer_smoke_script_prefers_exact_allowed_path(tmp_path: Path) -> None:
    smoke = tmp_path / "agent-docs" / "smoke-tests" / "PR-99-demo.sh"
    smoke.parent.mkdir(parents=True)
    smoke.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Demo Loop Task
status: todo
allowed_paths:
  - agent-docs/smoke-tests/PR-99-demo.sh
read_first: []
test_commands: []
rollback: Revert demo changes.
---

# PR-99
""",
    )

    task = load_task(task_path, tmp_path)

    assert infer_smoke_script(task, tmp_path) == smoke


def test_infer_smoke_script_fails_when_missing(tmp_path: Path) -> None:
    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Demo Loop Task
status: todo
allowed_paths:
  - src/api/**
read_first: []
test_commands: []
rollback: Revert demo changes.
---

# PR-99
""",
    )

    task = load_task(task_path, tmp_path)

    with pytest.raises(MissingSmokeScript):
        infer_smoke_script(task, tmp_path)


def test_infer_smoke_script_can_name_future_smoke_script(tmp_path: Path) -> None:
    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Demo Loop Task
status: todo
allowed_paths:
  - agent-docs/smoke-tests/**
read_first: []
test_commands: []
rollback: Revert demo changes.
---

# PR-99
""",
    )

    task = load_task(task_path, tmp_path)

    assert infer_smoke_script(task, tmp_path, require_exists=False) == (
        tmp_path / "agent-docs" / "smoke-tests" / "PR-99-demo.sh"
    )
    with pytest.raises(MissingSmokeScript):
        infer_smoke_script(task, tmp_path)


def test_infer_smoke_script_does_not_guess_by_duplicate_task_id(tmp_path: Path) -> None:
    smoke = tmp_path / "agent-docs" / "smoke-tests" / "PR-99-other-task.sh"
    smoke.parent.mkdir(parents=True)
    smoke.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Demo Loop Task
status: todo
allowed_paths:
  - src/api/**
read_first: []
test_commands: []
rollback: Revert demo changes.
---

# PR-99
""",
    )

    task = load_task(task_path, tmp_path)

    with pytest.raises(MissingSmokeScript):
        infer_smoke_script(task, tmp_path)


def test_infer_smoke_script_uses_task_filename_stem(tmp_path: Path) -> None:
    smoke = tmp_path / "agent-docs" / "smoke-tests" / "PR-99-demo.sh"
    smoke.parent.mkdir(parents=True)
    smoke.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Demo Loop Task
status: todo
allowed_paths:
  - src/api/**
read_first: []
test_commands: []
rollback: Revert demo changes.
---

# PR-99
""",
    )

    task = load_task(task_path, tmp_path)

    assert infer_smoke_script(task, tmp_path) == smoke


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
    for command in (
        ["git", "init", "-q"],
        ["git", "add", "-A"],
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"],
    ):
        subprocess.run(command, cwd=tmp_path, check=True)

    deleted.unlink()

    assert collect_changed_files(tmp_path) == ["src/outside_allowed.py"]


def test_discover_skills_matches_explicit_and_keywords(tmp_path: Path) -> None:
    explicit = tmp_path / "agent-docs" / "skills" / "api-task" / "SKILL.md"
    keyword = tmp_path / "agent-docs" / "skills" / "smoke-debugging" / "SKILL.md"
    explicit.parent.mkdir(parents=True)
    keyword.parent.mkdir(parents=True)
    explicit.write_text(
        """---
name: api-task
description: Execute API task docs.
---

# API task
""",
        encoding="utf-8",
    )
    keyword.write_text(
        """---
name: smoke-debugging
description: Debug smoke tests and local server verification.
---

# Smoke
""",
        encoding="utf-8",
    )
    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Smoke Verification
status: todo
allowed_paths:
  - agent-docs/smoke-tests/PR-99-demo.sh
read_first:
  - agent-docs/TESTING.md
test_commands: []
rollback: Revert demo changes.
loop:
  skills:
    - api-task
---

# PR-99
""",
    )

    task = load_task(task_path, tmp_path)
    skills = discover_skills(tmp_path, task)

    assert [skill.name for skill in skills] == ["api-task", "smoke-debugging"]
    assert all(skill.path.is_absolute() for skill in skills)


def test_discover_skills_does_not_keyword_match_role_skills(tmp_path: Path) -> None:
    role_skill = tmp_path / "agent-docs" / "skills" / "agent-docs-maker" / "SKILL.md"
    role_skill.parent.mkdir(parents=True)
    role_skill.write_text(
        """---
name: agent-docs-maker
description: Use as the maker role for agent-docs tasks.
---

# Maker
""",
        encoding="utf-8",
    )
    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Agent Docs Task
status: todo
allowed_paths:
  - agent-docs/smoke-tests/PR-99-demo.sh
read_first: []
test_commands: []
rollback: Revert demo changes.
---

# PR-99
""",
    )

    task = load_task(task_path, tmp_path)

    assert discover_skills(tmp_path, task) == []


def test_run_command_records_command_result(tmp_path: Path) -> None:
    result = run_command("python -c \"print('ok')\"", tmp_path, timeout_seconds=10)

    assert isinstance(result, CommandResult)
    assert result.exit_code == 0
    assert result.stdout.strip() == "ok"
    assert result.duration_seconds >= 0


def test_prepare_run_writes_prompts_and_run_json(tmp_path: Path) -> None:
    smoke = tmp_path / "agent-docs" / "smoke-tests" / "PR-99-demo.sh"
    smoke.parent.mkdir(parents=True)
    smoke.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Demo Loop Task
status: todo
allowed_paths:
  - agent-docs/smoke-tests/PR-99-demo.sh
read_first:
  - agent-docs/TESTING.md
test_commands:
  - python -c "print('ok')"
rollback: Revert demo changes.
---

# PR-99
""",
    )

    task = load_task(task_path, tmp_path)
    run = prepare_run(task, tmp_path, prepare_only=True)

    assert run.run_dir.exists()
    assert (run.run_dir / "maker-prompt.md").exists()
    assert (run.run_dir / "verifier-prompt.md").exists()
    run_json = json.loads((run.run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_json["task_id"] == "PR-99"
    assert run_json["status"] == "prepared"
    assert run_json["prepare_only"] is True
    assert run_json["verification"]["smoke_script"] == str(smoke)
    assert "python -c" in (run.run_dir / "maker-prompt.md").read_text(encoding="utf-8")


def test_prepare_run_allows_fresh_task_without_smoke_or_test_commands(tmp_path: Path) -> None:
    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Demo Loop Task
status: todo
allowed_paths:
  - agent-docs/smoke-tests/**
read_first:
  - agent-docs/TESTING.md
rollback: Revert demo changes.
---

# PR-99
""",
    )

    task = load_task(task_path, tmp_path)
    run = prepare_run(task, tmp_path, prepare_only=True)

    expected_smoke = tmp_path / "agent-docs" / "smoke-tests" / "PR-99-demo.sh"
    run_json = json.loads((run.run_dir / "run.json").read_text(encoding="utf-8"))
    maker_prompt = (run.run_dir / "maker-prompt.md").read_text(encoding="utf-8")

    assert run.smoke_script == expected_smoke
    assert run_json["verification"]["smoke_script"] == str(expected_smoke)
    assert run_json["verification"]["test_commands_missing"] is True
    assert "Missing from task frontmatter" in maker_prompt


def test_prepare_run_writes_agent_manifest_to_run_json(tmp_path: Path) -> None:
    smoke = tmp_path / "agent-docs" / "smoke-tests" / "PR-99-demo.sh"
    smoke.parent.mkdir(parents=True)
    smoke.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    local_maker = tmp_path / "agent-docs" / "skills" / "agent-docs-maker" / "SKILL.md"
    local_maker.parent.mkdir(parents=True)
    local_maker.write_text(
        """---
name: agent-docs-maker
description: Local maker role override.
---

# Local Maker
""",
        encoding="utf-8",
    )

    selected_skill = tmp_path / "agent-docs" / "skills" / "smoke-debugging" / "SKILL.md"
    selected_skill.parent.mkdir(parents=True)
    selected_skill.write_text(
        """---
name: smoke-debugging
description: Debug smoke verification failures.
---

# Smoke Debugging
""",
        encoding="utf-8",
    )

    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Smoke Verification
status: todo
allowed_paths:
  - agent-docs/smoke-tests/PR-99-demo.sh
read_first: []
test_commands: []
rollback: Revert demo changes.
---

# PR-99
""",
    )

    task = load_task(task_path, tmp_path)
    run = prepare_run(task, tmp_path, prepare_only=True)

    run_json = json.loads((run.run_dir / "run.json").read_text(encoding="utf-8"))
    agents = run_json["agents"]
    assert set(agents) == {"maker", "verifier", "reflection"}
    assert agents["maker"]["prompt"] == str(run.run_dir / "maker-prompt.md")
    assert agents["maker"]["role_skill_name"] == "agent-docs-maker"
    assert agents["maker"]["role_skill"] == str(local_maker)
    assert agents["verifier"]["role_skill"] == str(
        CORE_SKILLS_DIR / "agent-docs-verifier" / "SKILL.md"
    )
    assert [skill["name"] for skill in agents["maker"]["selected_skills"]] == [
        "smoke-debugging"
    ]
    assert agents["verifier"]["selected_skills"] == agents["maker"]["selected_skills"]
    assert agents["reflection"]["selected_skills"] == []
    assert run_json["skills"] == agents["maker"]["selected_skills"]


def test_prepare_run_injects_role_skills_when_present(tmp_path: Path) -> None:
    smoke = tmp_path / "agent-docs" / "smoke-tests" / "PR-99-demo.sh"
    smoke.parent.mkdir(parents=True)
    smoke.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    for name in ["agent-docs-maker", "agent-docs-verifier", "agent-docs-reflection"]:
        skill = tmp_path / "agent-docs" / "skills" / name / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            f"""---
name: {name}
description: Role skill for {name}.
---

# {name}
""",
            encoding="utf-8",
        )
    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Demo Loop Task
status: todo
allowed_paths:
  - agent-docs/smoke-tests/PR-99-demo.sh
read_first: []
test_commands: []
rollback: Revert demo changes.
---

# PR-99
""",
    )

    task = load_task(task_path, tmp_path)
    run = prepare_run(task, tmp_path, prepare_only=True)

    assert "agent-docs-maker" in (run.run_dir / "maker-prompt.md").read_text(encoding="utf-8")
    assert "red-green TDD" in (run.run_dir / "maker-prompt.md").read_text(encoding="utf-8")
    assert "agent-docs-verifier" in (run.run_dir / "verifier-prompt.md").read_text(encoding="utf-8")
    assert "agent-docs-reflection" in (run.run_dir / "reflection-prompt.md").read_text(encoding="utf-8")


def test_main_reports_runner_errors_without_traceback(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Demo Loop Task
status: todo
allowed_paths:
  - agent-docs/smoke-tests/PR-99-demo.sh
  - agent-docs/smoke-tests/PR-99-other.sh
read_first: []
test_commands: []
rollback: Revert demo changes.
---

# PR-99
""",
    )

    exit_code = main([str(task_path), "--repo-root", str(tmp_path), "--prepare-run"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "ERROR:" in captured.err
    assert "Multiple exact smoke scripts" in captured.err
    assert "Traceback" not in captured.err


def write_loop_config(repo_root: Path, body: str) -> Path:
    config_path = repo_root / "agent-docs" / "loop.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(body, encoding="utf-8")
    return config_path


def write_verifiable_task(repo_root: Path, smoke_body: str) -> Path:
    smoke = repo_root / "agent-docs" / "smoke-tests" / "PR-99-demo.sh"
    smoke.parent.mkdir(parents=True, exist_ok=True)
    smoke.write_text(smoke_body, encoding="utf-8")
    return write_task(
        repo_root,
        """---
id: PR-99
title: Demo Loop Task
status: todo
allowed_paths:
  - agent-docs/smoke-tests/PR-99-demo.sh
read_first: []
test_commands: []
rollback: Revert demo changes.
---

# PR-99
""",
    )


def smoke_gate(result) -> object:
    return next(gate for gate in result.gates if gate.name == "smoke_execution")


def test_verify_task_requires_smoke_script_to_exist(tmp_path: Path) -> None:
    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Demo Loop Task
status: todo
allowed_paths:
  - agent-docs/smoke-tests/PR-99-demo.sh
read_first: []
test_commands: []
rollback: Revert demo changes.
---

# PR-99
""",
    )

    task = load_task(task_path, tmp_path)
    result = verify_task(task, tmp_path, tmp_path / "run")

    smoke_exists_gate = next(gate for gate in result.gates if gate.name == "smoke_script_exists")
    assert not smoke_exists_gate.passed
    assert not smoke_gate(result).passed
    assert result.status == "failed"


def test_verify_task_fails_when_test_commands_frontmatter_missing(tmp_path: Path) -> None:
    smoke = tmp_path / "agent-docs" / "smoke-tests" / "PR-99-demo.sh"
    smoke.parent.mkdir(parents=True)
    smoke.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Demo Loop Task
status: todo
allowed_paths:
  - agent-docs/smoke-tests/PR-99-demo.sh
read_first: []
rollback: Revert demo changes.
---

# PR-99
""",
    )

    task = load_task(task_path, tmp_path)
    result = verify_task(task, tmp_path, tmp_path / "run")

    test_commands_gate = next(gate for gate in result.gates if gate.name == "test_commands_defined")
    assert not test_commands_gate.passed
    assert smoke_gate(result).passed
    assert result.status == "failed"


def test_load_project_config_defaults_when_missing(tmp_path: Path) -> None:
    config = load_project_config(tmp_path)

    assert config.api_key_env is None
    assert config.services == []


def test_load_project_config_parses_api_key_env_and_services(tmp_path: Path) -> None:
    write_loop_config(
        tmp_path,
        """api_key_env: DEMO_API_KEY
services:
  - name: db
    command: docker compose up -d db
    health_url: http://127.0.0.1:5999/
    health_headers:
      apikey: local
    startup_timeout_seconds: 30
  - name: server
    command: run server
    cwd: app
    background: true
    env:
      FOO: bar
""",
    )

    config = load_project_config(tmp_path)

    assert config.api_key_env == "DEMO_API_KEY"
    db, server = config.services
    assert db.name == "db"
    assert db.command == "docker compose up -d db"
    assert db.background is False
    assert db.health_url == "http://127.0.0.1:5999/"
    assert db.health_headers == {"apikey": "local"}
    assert db.startup_timeout_seconds == 30
    assert db.cwd is None
    assert server.name == "server"
    assert server.cwd == "app"
    assert server.background is True
    assert server.env == {"FOO": "bar"}
    assert server.health_url is None


def test_load_project_config_rejects_service_without_command(tmp_path: Path) -> None:
    write_loop_config(tmp_path, "services:\n  - name: db\n")

    with pytest.raises(ProjectConfigError):
        load_project_config(tmp_path)


def test_verify_task_runs_smoke_without_api_key_when_not_configured(tmp_path: Path) -> None:
    task_path = write_verifiable_task(
        tmp_path,
        '#!/usr/bin/env bash\nif [ "$#" -ne 0 ]; then exit 1; fi\nexit 0\n',
    )

    task = load_task(task_path, tmp_path)
    result = verify_task(task, tmp_path, tmp_path / "run")

    assert smoke_gate(result).passed
    assert result.status == "needs_verifier"


def test_verify_task_fails_smoke_when_configured_api_key_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEMO_API_KEY", raising=False)
    write_loop_config(tmp_path, "api_key_env: DEMO_API_KEY\n")
    task_path = write_verifiable_task(tmp_path, "#!/usr/bin/env bash\nexit 0\n")

    task = load_task(task_path, tmp_path)
    result = verify_task(task, tmp_path, tmp_path / "run")

    assert not smoke_gate(result).passed
    assert result.status == "failed"
    smoke_json = json.loads((tmp_path / "run" / "smoke.json").read_text(encoding="utf-8"))
    assert "DEMO_API_KEY" in smoke_json["stderr"]


def test_verify_task_passes_configured_api_key_as_first_arg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_API_KEY", "sekret")
    write_loop_config(tmp_path, "api_key_env: DEMO_API_KEY\n")
    task_path = write_verifiable_task(
        tmp_path,
        '#!/usr/bin/env bash\n[ "$1" = "sekret" ] || exit 1\n',
    )

    task = load_task(task_path, tmp_path)
    result = verify_task(task, tmp_path, tmp_path / "run")

    assert smoke_gate(result).passed


def test_verify_task_starts_configured_services_before_smoke(tmp_path: Path) -> None:
    write_loop_config(
        tmp_path,
        "services:\n  - name: marker\n    command: touch service-started.marker\n",
    )
    task_path = write_verifiable_task(
        tmp_path,
        "#!/usr/bin/env bash\n[ -f service-started.marker ] || exit 1\n",
    )

    task = load_task(task_path, tmp_path)
    result = verify_task(task, tmp_path, tmp_path / "run")

    assert smoke_gate(result).passed
    assert (tmp_path / "run" / "marker-start.json").exists()


def test_verify_task_terminates_background_services_after_smoke(tmp_path: Path) -> None:
    write_loop_config(
        tmp_path,
        "services:\n"
        "  - name: sleeper\n"
        "    command: echo $$ > bg.pid && sleep 30\n"
        "    background: true\n",
    )
    task_path = write_verifiable_task(
        tmp_path,
        "#!/usr/bin/env bash\n"
        "for _ in $(seq 1 50); do [ -f bg.pid ] && exit 0; sleep 0.1; done\n"
        "exit 1\n",
    )

    task = load_task(task_path, tmp_path)
    result = verify_task(task, tmp_path, tmp_path / "run")

    assert smoke_gate(result).passed
    pid = int((tmp_path / "bg.pid").read_text(encoding="utf-8").strip())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_prepare_run_falls_back_to_core_role_skills(tmp_path: Path) -> None:
    smoke = tmp_path / "agent-docs" / "smoke-tests" / "PR-99-demo.sh"
    smoke.parent.mkdir(parents=True)
    smoke.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    task_path = write_task(
        tmp_path,
        """---
id: PR-99
title: Demo Loop Task
status: todo
allowed_paths:
  - agent-docs/smoke-tests/PR-99-demo.sh
read_first: []
test_commands: []
rollback: Revert demo changes.
---

# PR-99
""",
    )

    task = load_task(task_path, tmp_path)
    run = prepare_run(task, tmp_path, prepare_only=True)

    maker_prompt = (run.run_dir / "maker-prompt.md").read_text(encoding="utf-8")
    assert str(CORE_SKILLS_DIR / "agent-docs-maker" / "SKILL.md") in maker_prompt


def test_verify_task_ignores_runner_owned_run_artifacts(tmp_path: Path) -> None:
    task_path = write_verifiable_task(tmp_path, "#!/usr/bin/env bash\nexit 0\n")
    for command in (
        ["git", "init", "-q"],
        ["git", "add", "-A"],
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"],
    ):
        subprocess.run(command, cwd=tmp_path, check=True)

    task = load_task(task_path, tmp_path)
    run = prepare_run(task, tmp_path, prepare_only=True)
    result = verify_task(task, tmp_path, run.run_dir)

    diff_gate = next(gate for gate in result.gates if gate.name == "diff_scope")
    assert diff_gate.passed, diff_gate.details
    assert result.status == "needs_verifier"


def test_verify_task_flags_deleted_file_outside_allowed_paths(tmp_path: Path) -> None:
    task_path = write_verifiable_task(tmp_path, "#!/usr/bin/env bash\nexit 0\n")
    outside_allowed = tmp_path / "src" / "outside_allowed.py"
    outside_allowed.parent.mkdir()
    outside_allowed.write_text("old\n", encoding="utf-8")
    for command in (
        ["git", "init", "-q"],
        ["git", "add", "-A"],
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"],
    ):
        subprocess.run(command, cwd=tmp_path, check=True)
    outside_allowed.unlink()

    task = load_task(task_path, tmp_path)
    result = verify_task(task, tmp_path, tmp_path / "run")

    diff_gate = next(gate for gate in result.gates if gate.name == "diff_scope")
    assert not diff_gate.passed
    assert diff_gate.details["changed_files"] == ["src/outside_allowed.py"]
    assert diff_gate.details["violations"] == ["src/outside_allowed.py"]
    assert result.status == "failed"
