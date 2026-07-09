#!/usr/bin/env python3
# ABOUTME: Installs this repo's local agent skills for supported coding agents.
# ABOUTME: Copies repo-local skills safely, skipping existing installs by default.

from __future__ import annotations

import argparse
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillInstall:
    agent: str
    name: str
    source: Path
    destination: Path
    status: str
    kind: str = "skill"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install this repo's local agent skills."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=_repo_root() / "skills",
        help="Directory containing local skills; defaults to ./skills",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        help="Codex skills destination. Alias for --codex-dest.",
    )
    parser.add_argument(
        "--codex-dest",
        type=Path,
        default=_default_codex_skills_dir(),
        help="Codex skills destination; defaults to ${CODEX_HOME:-~/.codex}/skills",
    )
    parser.add_argument(
        "--claude-dir",
        type=Path,
        default=_default_claude_dir(),
        help="Claude config directory; defaults to ${CLAUDE_HOME:-~/.claude}",
    )
    parser.add_argument(
        "--skill",
        action="append",
        default=[],
        help="Skill name to install. May be repeated. Defaults to all local skills.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing installed skill directories.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned installs without copying files.",
    )
    args = parser.parse_args()

    installs: list[SkillInstall] = []
    codex_dest = args.dest if args.dest is not None else args.codex_dest
    installs.extend(
        install_codex_skills(
            source_dir=args.source,
            dest_dir=codex_dest,
            requested=args.skill,
            force=args.force,
            dry_run=args.dry_run,
        )
    )
    installs.extend(
        install_claude_assets(
            source_dir=args.source,
            claude_dir=args.claude_dir,
            requested=args.skill,
            force=args.force,
            dry_run=args.dry_run,
        )
    )
    for install in installs:
        print(
            f"{install.agent}:{install.status}: "
            f"{install.kind}:{install.name} -> {install.destination}"
        )
    return 0


def install_codex_skills(
    *,
    source_dir: Path,
    dest_dir: Path,
    requested: list[str],
    force: bool = False,
    dry_run: bool = False,
) -> list[SkillInstall]:
    source = source_dir.resolve()
    destination = dest_dir.expanduser().resolve()
    skills = _discover_skills(source, requested)
    if not skills:
        raise SystemExit(f"No skills found in {source}")

    installs: list[SkillInstall] = []
    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)

    for name, skill_source in skills.items():
        skill_dest = destination / name
        status = "installed"
        if skill_dest.exists():
            if not force:
                installs.append(
                    SkillInstall(
                        agent="codex",
                        name=name,
                        source=skill_source,
                        destination=skill_dest,
                        status="skipped-existing",
                    )
                )
                continue
            status = "replaced"
            if not dry_run:
                shutil.rmtree(skill_dest)

        if dry_run:
            status = "would-replace" if skill_dest.exists() and force else "would-install"
        else:
            shutil.copytree(skill_source, skill_dest)

        installs.append(
            SkillInstall(
                agent="codex",
                name=name,
                source=skill_source,
                destination=skill_dest,
                status=status,
            )
        )

    return installs


def install_claude_assets(
    *,
    source_dir: Path,
    claude_dir: Path,
    requested: list[str],
    force: bool = False,
    dry_run: bool = False,
) -> list[SkillInstall]:
    source = source_dir.resolve()
    root = _repo_root()
    claude_root = claude_dir.expanduser().resolve()
    skills = _discover_skills(source, requested)
    if not skills:
        raise SystemExit(f"No skills found in {source}")

    installs: list[SkillInstall] = []
    claude_skills = claude_root / "skills"
    claude_commands = claude_root / "commands"
    if not dry_run:
        claude_skills.mkdir(parents=True, exist_ok=True)
        claude_commands.mkdir(parents=True, exist_ok=True)

    for name, skill_source in skills.items():
        skill_dest = claude_skills / name
        installs.append(
            _copy_skill(
                agent="claude",
                name=name,
                source=skill_source,
                destination=skill_dest,
                force=force,
                dry_run=dry_run,
            )
        )
        command_dest = claude_commands / f"{name}.md"
        installs.append(
            _write_claude_command(
                name=name,
                skill_path=skill_dest / "SKILL.md",
                agent_core_root=root,
                destination=command_dest,
                force=force,
                dry_run=dry_run,
            )
        )

    return installs


def _copy_skill(
    *,
    agent: str,
    name: str,
    source: Path,
    destination: Path,
    force: bool,
    dry_run: bool,
) -> SkillInstall:
    status = "installed"
    if destination.exists():
        if not force:
            return SkillInstall(
                agent=agent,
                name=name,
                source=source,
                destination=destination,
                status="skipped-existing",
            )
        status = "replaced"
        if not dry_run:
            shutil.rmtree(destination)

    if dry_run:
        status = "would-replace" if destination.exists() and force else "would-install"
    else:
        shutil.copytree(source, destination)

    return SkillInstall(
        agent=agent,
        name=name,
        source=source,
        destination=destination,
        status=status,
    )


def _write_claude_command(
    *,
    name: str,
    skill_path: Path,
    agent_core_root: Path,
    destination: Path,
    force: bool,
    dry_run: bool,
) -> SkillInstall:
    status = "installed"
    if destination.exists():
        if not force:
            return SkillInstall(
                agent="claude",
                name=name,
                source=skill_path,
                destination=destination,
                status="skipped-existing",
                kind="command",
            )
        status = "replaced"

    if dry_run:
        status = "would-replace" if destination.exists() and force else "would-install"
    else:
        destination.write_text(
            _claude_command(name, skill_path, agent_core_root),
            encoding="utf-8",
        )

    return SkillInstall(
        agent="claude",
        name=name,
        source=skill_path,
        destination=destination,
        status=status,
        kind="command",
    )


def _claude_command(name: str, skill_path: Path, agent_core_root: Path) -> str:
    return f"""---
description: Run the {name} workflow from agent-core.
---

Read and follow this installed skill:

```text
{skill_path}
```

Use this agent-core checkout for `<agent-core>` command placeholders:

```text
{agent_core_root}
```

If the user has not provided an `agent-docs/tasks/*.md` file, run the skill's
Intake Mode. If the user has provided a task file, run Execution Mode.

Treat the current working directory as `<target-repo>` unless the user gives a
different repo path.

User request:

$ARGUMENTS
"""


def _discover_skills(source_dir: Path, requested: list[str]) -> dict[str, Path]:
    if not source_dir.exists():
        raise SystemExit(f"Skill source directory does not exist: {source_dir}")

    available = {
        path.name: path
        for path in sorted(source_dir.iterdir())
        if path.is_dir() and (path / "SKILL.md").is_file()
    }
    if not requested:
        return available

    missing = [name for name in requested if name not in available]
    if missing:
        raise SystemExit(f"Unknown local skill(s): {', '.join(missing)}")
    return {name: available[name] for name in requested}


def _default_codex_skills_dir() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home) / "skills"
    return Path.home() / ".codex" / "skills"


def _default_claude_dir() -> Path:
    claude_home = os.environ.get("CLAUDE_HOME")
    if claude_home:
        return Path(claude_home)
    return Path.home() / ".claude"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    raise SystemExit(main())
