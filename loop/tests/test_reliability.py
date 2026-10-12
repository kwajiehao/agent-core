"""Behavioral regressions for scope, evidence binding and command lifecycle."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from loop import runner  # noqa: E402


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def make_task(root: Path, *, command: str = "true", review: bool = False) -> runner.TaskSpec:
    root.mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "main.py").write_text("value = 1\n", encoding="utf-8")
    (root / "notes.txt").write_text("user original\n", encoding="utf-8")
    task_path = root / "agent-docs" / "tasks" / "CHECK-demo.md"
    task_path.parent.mkdir(parents=True)
    coordination = {
        "mode": "review" if review else "solo",
        "reviewer": {"characterization": "Python regression reviewer"},
    }
    import yaml

    task_path.write_text(
        "---\n" + yaml.safe_dump({
            "id": "CHECK", "title": "Demonstrate required behavior",
            "allowed_paths": ["src/**"], "test_commands": [command],
            "coordination": coordination,
            "acceptance": [{"condition": "The declared behavior check succeeds", "command": command}],
        }) + "---\n\nThe original task contract.\n", encoding="utf-8",
    )
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-qm", "baseline")
    return runner.load_task(task_path, root)


def gate(result: runner.VerificationResult, name: str) -> runner.GateResult:
    return next(item for item in result.gates if item.name == name)


def test_cli_relative_task_and_run_paths_use_explicit_repository_root(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "project"
    task = make_task(root, review=True)
    monkeypatch.chdir(tmp_path)
    task_relative = task.path.relative_to(root).as_posix()
    assert runner.main([task_relative, "--repo-root", str(root), "--prepare-run"]) == 0
    output = capsys.readouterr().out
    run_dir = Path(next(line.removeprefix("run_dir=") for line in output.splitlines() if line.startswith("run_dir=")))
    (run_dir / "subagents" / "reviewer.md").write_text("Independent review.\nVerdict: approve\n")
    assert runner.main([task_relative, "--repo-root", str(root), "--record-review",
                        "--run-dir", run_dir.relative_to(root).as_posix()]) == 0
    assert runner.main([task_relative, "--repo-root", str(root), "--verify-only",
                        "--run-dir", run_dir.relative_to(root).as_posix()]) == 0
    assert json.loads((run_dir / "verification.json").read_text())["status"] == "passed"


def test_dirty_file_additional_edit_is_not_exempt(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    (tmp_path / "notes.txt").write_text("human pending change\n", encoding="utf-8")
    run = runner.prepare_run(task, tmp_path)
    (tmp_path / "notes.txt").write_text("agent overwrote human change\n", encoding="utf-8")
    result = runner.verify_task(task, tmp_path, run.run_dir)
    assert result.status == "failed"
    assert "notes.txt" in gate(result, "diff_scope").details["violations"]


def test_unchanged_dirty_file_is_preserved_and_exempt(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    (tmp_path / "notes.txt").write_text("human pending change\n", encoding="utf-8")
    run = runner.prepare_run(task, tmp_path)
    result = runner.verify_task(task, tmp_path, run.run_dir)
    assert result.status == "passed"
    assert (tmp_path / "notes.txt").read_text() == "human pending change\n"


def test_committed_forbidden_edit_is_seen(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    run = runner.prepare_run(task, tmp_path)
    (tmp_path / "notes.txt").write_text("forbidden committed edit\n", encoding="utf-8")
    git(tmp_path, "add", "notes.txt")
    git(tmp_path, "-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-qm", "agent change")
    result = runner.verify_task(task, tmp_path, run.run_dir)
    assert result.status == "failed"
    assert "notes.txt" in gate(result, "diff_scope").details["violations"]


def test_test_command_mutation_is_checked_after_execution(tmp_path: Path) -> None:
    task = make_task(tmp_path, command="printf changed > notes.txt")
    run = runner.prepare_run(task, tmp_path)
    result = runner.verify_task(task, tmp_path, run.run_dir)
    assert result.status == "failed"
    assert "notes.txt" in gate(result, "diff_scope").details["violations"]


def test_only_current_run_artifacts_are_exempt(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    run = runner.prepare_run(task, tmp_path)
    foreign = tmp_path / "agent-docs" / "runs" / "OTHER" / "other-run" / "handoff.md"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("unrelated task modified", encoding="utf-8")
    result = runner.verify_task(task, tmp_path, run.run_dir)
    assert result.status == "failed"
    assert foreign.relative_to(tmp_path).as_posix() in gate(result, "diff_scope").details["violations"]


def test_prepare_fails_closed_outside_git(tmp_path: Path) -> None:
    with pytest.raises(runner.RunnerError, match="[Gg]it"):
        runner.collect_changed_files(tmp_path)


def test_prepare_requires_actual_repository_root(tmp_path: Path) -> None:
    make_task(tmp_path)
    with pytest.raises(runner.RunnerError, match="root"):
        runner.collect_changed_files(tmp_path / "src")


def test_changed_task_contract_cannot_silently_replace_snapshot(tmp_path: Path) -> None:
    task = make_task(tmp_path, command="false")
    run = runner.prepare_run(task, tmp_path)
    task.path.write_text(task.path.read_text().replace("false", "true"), encoding="utf-8")
    altered = runner.load_task(task.path, tmp_path)
    with pytest.raises(runner.RunnerError, match="task.*changed|snapshot"):
        runner.verify_task(altered, tmp_path, run.run_dir)


def test_prepared_task_snapshot_preserves_exact_bytes(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    run = runner.prepare_run(task, tmp_path)
    assert (run.run_dir / "task.snapshot.md").read_bytes() == task.path.read_bytes()
    assert json.loads((run.run_dir / "run.json").read_text())["schema_version"] == 2


def test_verify_requires_prepared_baseline(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    with pytest.raises(runner.RunnerError, match="prepare|baseline"):
        runner.verify_task(task, tmp_path, tmp_path / "arbitrary-run")


def test_review_text_requires_recorded_patch_binding(tmp_path: Path) -> None:
    task = make_task(tmp_path, review=True)
    run = runner.prepare_run(task, tmp_path)
    (run.run_dir / "subagents" / "reviewer.md").write_text("Verdict: approve\n", encoding="utf-8")
    result = runner.verify_task(task, tmp_path, run.run_dir)
    assert result.status == "failed"
    assert not gate(result, "coordination").passed


def test_record_review_is_valid_until_code_changes(tmp_path: Path) -> None:
    task = make_task(tmp_path, review=True)
    run = runner.prepare_run(task, tmp_path)
    (run.run_dir / "subagents" / "reviewer.md").write_text("Checked behavior.\nVerdict: approve\n", encoding="utf-8")
    runner.record_review(task, tmp_path, run.run_dir)
    assert runner.verify_task(task, tmp_path, run.run_dir).status == "passed"
    (tmp_path / "src" / "main.py").write_text("value = 2\n", encoding="utf-8")
    result = runner.verify_task(task, tmp_path, run.run_dir)
    assert result.status == "failed"
    assert not gate(result, "coordination").passed


def test_reviewer_artifact_change_invalidates_binding(tmp_path: Path) -> None:
    task = make_task(tmp_path, review=True)
    run = runner.prepare_run(task, tmp_path)
    reviewer = run.run_dir / "subagents" / "reviewer.md"
    reviewer.write_text("Verdict: approve\n", encoding="utf-8")
    runner.record_review(task, tmp_path, run.run_dir)
    reviewer.write_text("New findings after recording.\nVerdict: approve\n", encoding="utf-8")
    assert runner.verify_task(task, tmp_path, run.run_dir).status == "failed"


def test_resume_rejects_status_only_verification(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    run = runner.prepare_run(task, tmp_path)
    (run.run_dir / "verification.json").write_text('{"status":"passed"}', encoding="utf-8")
    result = runner.discover_resume(tmp_path)
    assert result.action == "resume"
    assert result.verification_status == "invalid"
    assert result.warnings


def test_resume_rejects_pass_for_changed_code(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    run = runner.prepare_run(task, tmp_path)
    assert runner.verify_task(task, tmp_path, run.run_dir).status == "passed"
    (tmp_path / "src" / "main.py").write_text("value = 2\n", encoding="utf-8")
    result = runner.discover_resume(tmp_path)
    assert result.action == "resume"
    assert result.verification_status == "invalid"


def test_resume_rejects_pass_for_changed_task_body(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    run = runner.prepare_run(task, tmp_path)
    assert runner.verify_task(task, tmp_path, run.run_dir).status == "passed"
    task.path.write_text(task.path.read_text() + "New requirement\n", encoding="utf-8")
    assert runner.discover_resume(tmp_path).verification_status == "invalid"


def test_acceptance_maps_conditions_to_command_results(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    run = runner.prepare_run(task, tmp_path)
    result = runner.verify_task(task, tmp_path, run.run_dir)
    acceptance = gate(result, "acceptance")
    assert acceptance.passed
    assert acceptance.details["conditions"][0]["condition"] == "The declared behavior check succeeds"
    assert acceptance.details["conditions"][0]["command"] == "true"
    assert acceptance.details["conditions"][0]["passed"] is True


def test_missing_acceptance_mapping_fails_prepare(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    import yaml

    frontmatter, body = runner._read_frontmatter(task.path)
    frontmatter.pop("acceptance")
    task.path.write_text("---\n" + yaml.safe_dump(frontmatter) + "---\n" + body, encoding="utf-8")
    with pytest.raises(runner.FrontmatterError, match="acceptance"):
        runner.prepare_run(runner.load_task(task.path, tmp_path), tmp_path)


def test_acceptance_cannot_reference_undeclared_command(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    task.path.write_text(task.path.read_text().replace("command: 'true'", "command: pytest nonexistent.py"), encoding="utf-8")
    with pytest.raises(runner.FrontmatterError, match="declared|acceptance"):
        runner.load_task(task.path, tmp_path)


@pytest.mark.skipif(os.name != "posix", reason="Process group behavior uses POSIX")
def test_timeout_kills_descendant_that_would_write_later(tmp_path: Path) -> None:
    proof = tmp_path / "child-survived.txt"
    child = f"import time; time.sleep(0.5); open({str(proof)!r}, 'w').write('survived')"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(child)}; true"
    result = runner.run_command(command, tmp_path, timeout_seconds=0.1)
    time.sleep(0.6)
    assert result.timed_out
    assert not proof.exists()


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_malformed_utf8_retention_reports_decoded_clipping(tmp_path: Path, stream: str) -> None:
    from loop.process import MAX_OUTPUT_BYTES, capture_command

    command = shlex.join([sys.executable, "-c",
                          f"import sys; sys.{stream}.buffer.write(bytes([255]) * 30000)"])
    result = capture_command(command, tmp_path, 5)
    assert result.exit_code == 0
    assert len(getattr(result, stream).encode()) <= MAX_OUTPUT_BYTES
    assert getattr(result, f"{stream}_truncated") is True
    other = "stderr" if stream == "stdout" else "stdout"
    assert getattr(result, other) == ""
    assert getattr(result, f"{other}_truncated") is False


def test_output_retention_is_bounded_and_reports_truncation(tmp_path: Path) -> None:
    code = "import sys; sys.stdout.write('a'*2000000); sys.stderr.write('b'*2000000)"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"
    result = runner.run_command(command, tmp_path, timeout_seconds=10)
    assert result.exit_code == 0
    assert len(result.stdout.encode()) <= 65536
    assert len(result.stderr.encode()) <= 65536
    assert result.stdout_truncated and result.stderr_truncated


def test_review_cli_records_binding(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    task = make_task(tmp_path, review=True)
    run = runner.prepare_run(task, tmp_path)
    (run.run_dir / "subagents" / "reviewer.md").write_text("Verdict: approve\n", encoding="utf-8")
    assert runner.main([str(task.path), "--repo-root", str(tmp_path), "--record-review", "--run-dir", str(run.run_dir)]) == 0
    assert json.loads(capsys.readouterr().out)["task_sha256"]
    assert runner.verify_task(task, tmp_path, run.run_dir).status == "passed"


def test_resume_rejects_changed_reviewer_after_pass(tmp_path: Path) -> None:
    task = make_task(tmp_path, review=True)
    run = runner.prepare_run(task, tmp_path)
    reviewer = run.run_dir / "subagents" / "reviewer.md"
    reviewer.write_text("Verdict: approve\n", encoding="utf-8")
    runner.record_review(task, tmp_path, run.run_dir)
    assert runner.verify_task(task, tmp_path, run.run_dir).status == "passed"
    reviewer.write_text("Unreviewed revision.\nVerdict: approve\n", encoding="utf-8")
    assert runner.discover_resume(tmp_path).verification_status == "invalid"


def test_interrupted_reverification_invalidates_previous_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task = make_task(tmp_path)
    run = runner.prepare_run(task, tmp_path)
    assert runner.verify_task(task, tmp_path, run.run_dir).status == "passed"

    def interrupt(command: str, cwd: Path, timeout_seconds: int) -> runner.CommandResult:
        raise KeyboardInterrupt("simulated user interruption")

    monkeypatch.setattr(runner, "run_command", interrupt)
    with pytest.raises(KeyboardInterrupt):
        runner.verify_task(task, tmp_path, run.run_dir)
    assert json.loads((run.run_dir / "verification.json").read_text())["status"] == "running"
    assert runner.discover_resume(tmp_path).verification_status == "invalid"


def test_same_run_cannot_verify_concurrently(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    run = runner.prepare_run(task, tmp_path)
    with runner._artifact_lock(run.run_dir):
        with pytest.raises(runner.RunnerError, match="another verification"):
            runner.verify_task(task, tmp_path, run.run_dir)


def test_commands_changing_allowed_code_require_reverification(tmp_path: Path) -> None:
    task = make_task(tmp_path, command="printf 'value = 2' > src/main.py")
    run = runner.prepare_run(task, tmp_path)
    result = runner.verify_task(task, tmp_path, run.run_dir)
    assert gate(result, "diff_scope").passed
    assert not gate(result, "snapshot_stability").passed
    assert runner.verify_task(task, tmp_path, run.run_dir).status == "passed"


def test_acceptance_requires_nonempty_evidence_and_binds_its_hash(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    import yaml

    metadata, body = runner._read_frontmatter(task.path)
    metadata["acceptance"][0]["evidence"] = "src/proof.txt"
    task.path.write_text("---\n" + yaml.safe_dump(metadata) + "---\n" + body, encoding="utf-8")
    task = runner.load_task(task.path, tmp_path)
    run = runner.prepare_run(task, tmp_path)
    assert not gate(runner.verify_task(task, tmp_path, run.run_dir), "acceptance").passed
    (tmp_path / "src" / "proof.txt").write_text("observed result", encoding="utf-8")
    result = runner.verify_task(task, tmp_path, run.run_dir)
    condition = gate(result, "acceptance").details["conditions"][0]
    assert result.status == "passed"
    assert condition["evidence_sha256"]
    (tmp_path / "src" / "proof.txt").write_text("different result", encoding="utf-8")
    assert runner.discover_resume(tmp_path).verification_status == "invalid"


def test_legacy_runs_are_retained_with_explicit_upgrade_warning(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    run = runner.prepare_run(task, tmp_path)
    metadata_path = run.run_dir / "run.json"
    metadata = json.loads(metadata_path.read_text())
    metadata.pop("schema_version")
    metadata.pop("baseline")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    result = runner.discover_resume(tmp_path)
    assert result.run_dir == str(run.run_dir)
    assert any("legacy" in warning.lower() and "v2" in warning for warning in result.warnings)
    with pytest.raises(runner.RunnerError, match="legacy"):
        runner.verify_task(task, tmp_path, run.run_dir)


def test_generated_prompt_uses_available_runtime_and_memory(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    (tmp_path / "agent-docs" / "MEMORY.md").write_text("Use the existing service", encoding="utf-8")
    run = runner.prepare_run(task, tmp_path)
    prompt = (run.run_dir / "prompt.md").read_text()
    assert str(sys.executable) in prompt
    assert "task.snapshot.md" in prompt
    assert "MEMORY.md" in prompt
    assert "acceptance" in prompt.lower()
    assert "opus-4.8" not in prompt


def test_git_executable_missing_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_task(tmp_path)
    monkeypatch.setenv("PATH", "")
    with pytest.raises(runner.RunnerError, match="Git"):
        runner.collect_changed_files(tmp_path)


def test_missing_head_object_is_not_treated_as_unborn_repository(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    reference = subprocess.run(["git", "symbolic-ref", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()
    (tmp_path / ".git" / reference).write_text("a" * 40 + "\n", encoding="utf-8")
    with pytest.raises(runner.RunnerError, match="Git"):
        runner.prepare_run(task, tmp_path)


def test_unborn_git_branch_is_supported(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    git(tmp_path, "update-ref", "-d", "HEAD")
    run = runner.prepare_run(task, tmp_path)
    assert json.loads((run.run_dir / "run.json").read_text())["baseline"]["head"] is None
    assert runner.verify_task(task, tmp_path, run.run_dir).status == "passed"


def test_record_review_reports_invalid_utf8_without_traceback(tmp_path: Path) -> None:
    task = make_task(tmp_path, review=True)
    run = runner.prepare_run(task, tmp_path)
    (run.run_dir / "subagents" / "reviewer.md").write_bytes(b"\xffVerdict: approve")
    with pytest.raises(runner.RunnerError, match="reviewer"):
        runner.record_review(task, tmp_path, run.run_dir)


def test_malformed_yaml_is_a_task_contract_error(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    task.path.write_text("---\nid: [unterminated\n---\n", encoding="utf-8")
    with pytest.raises(runner.FrontmatterError, match="frontmatter"):
        runner.load_task(task.path, tmp_path)


def test_create_task_rejects_invalid_command_mapping_before_writing(tmp_path: Path) -> None:
    with pytest.raises(runner.FrontmatterError, match="declared"):
        runner.create_task(tmp_path, task_id="NEW", title="Add behavior", read_first=[], allowed_paths=["src/**"], test_commands=["true"], acceptance=[runner.AcceptanceSpec("The behavior check succeeds", "undeclared-check")])
    assert not (tmp_path / "agent-docs").exists()


def test_new_prepared_run_supersedes_legacy_attempt_for_same_task(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    legacy = runner.prepare_run(task, tmp_path)
    metadata_path = legacy.run_dir / "run.json"
    metadata = json.loads(metadata_path.read_text())
    metadata.pop("schema_version")
    metadata["created_at"] = "2020-01-01T00:00:00+00:00"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    current = runner.prepare_run(task, tmp_path)
    assert runner.verify_task(task, tmp_path, current.run_dir).status == "passed"
    result = runner.discover_resume(tmp_path)
    assert result.action == "completed_context"
    assert result.run_dir == str(current.run_dir)
    assert legacy.run_dir.exists()
