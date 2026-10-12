"""Installer behavior against isolated destinations, including foreign symlinks."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install_skills.py"
SPEC = importlib.util.spec_from_file_location("skill_installer_under_test", SCRIPT)
installer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = installer
SPEC.loader.exec_module(installer)


def test_default_uses_canonical_discovery_path(monkeypatch, tmp_path):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert installer._default_codex_skills_dir() == tmp_path / ".agents" / "skills"


def test_explicit_codex_home_is_preserved(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "configured"))
    assert installer._default_codex_skills_dir() == tmp_path / "configured" / "skills"


@pytest.mark.parametrize("force", [False, True])
def test_foreign_skill_symlink_never_deletes_target(tmp_path, force):
    source = tmp_path / "source" / "sample"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("---\nname: sample\ndescription: sample\n---\nNew skill\n")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "valuable.txt").write_text("keep me")
    destination = tmp_path / "skills"
    destination.mkdir()
    (destination / "sample").symlink_to(foreign, target_is_directory=True)
    installs = installer.install_codex_skills(
        source_dir=source.parent, dest_dir=destination, requested=[], force=force,
    )
    assert (foreign / "valuable.txt").read_text() == "keep me"
    if force:
        assert not (destination / "sample").is_symlink()
        assert (destination / "sample" / "SKILL.md").read_text().endswith("New skill\n")
        assert installs[0].status == "replaced"
    else:
        assert (destination / "sample").is_symlink()
        assert installs[0].status == "skipped-existing"


def test_dangling_symlink_is_preserved_without_force(tmp_path):
    source = tmp_path / "source" / "sample"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("---\nname: sample\ndescription: sample\n---\n")
    destination = tmp_path / "skills"
    destination.mkdir()
    link = destination / "sample"
    link.symlink_to(tmp_path / "missing")
    installs = installer.install_codex_skills(source_dir=source.parent, dest_dir=destination, requested=[])
    assert link.is_symlink()
    assert installs[0].status == "skipped-existing"


def test_installed_loop_can_locate_its_runner(tmp_path):
    destination = tmp_path / "skills"
    installer.install_codex_skills(
        source_dir=SCRIPT.parents[1] / "skills", dest_dir=destination, requested=["agent-docs-loop"],
    )
    metadata = json.loads((destination / "agent-docs-loop" / "references" / "installation.json").read_text())
    assert Path(metadata["agent_core_root"]) / "loop" / "run_task.py" == SCRIPT.parents[1] / "loop" / "run_task.py"
    assert (Path(metadata["agent_core_root"]) / "loop" / "run_task.py").is_file()


@pytest.mark.parametrize("force", [False, True])
def test_claude_adapter_symlink_preserves_foreign_file(tmp_path, force):
    target = tmp_path / "foreign-command.md"
    target.write_text("user-owned command")
    destination = tmp_path / "loop-command.md"
    destination.symlink_to(target)
    installer._write_claude_command(
        name="agent-docs-loop", skill_path=tmp_path / "skill" / "SKILL.md",
        agent_core_root=SCRIPT.parents[1], destination=destination, force=force, dry_run=False,
    )
    assert target.read_text() == "user-owned command"
    assert destination.is_symlink() is not force
