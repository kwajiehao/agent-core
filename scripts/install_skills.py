#!/usr/bin/env python3
# ABOUTME: Installs this repo's Codex skills into the user's Codex skills dir.
# ABOUTME: Copies repo-local skills safely, skipping existing installs by default.

from __future__ import annotations

import argparse
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillInstall:
    name: str
    source: Path
    destination: Path
    status: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install this repo's local Codex skills."
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
        default=_default_skills_dir(),
        help="Destination skills directory; defaults to ${CODEX_HOME:-~/.codex}/skills",
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

    installs = install_skills(
        source_dir=args.source,
        dest_dir=args.dest,
        requested=args.skill,
        force=args.force,
        dry_run=args.dry_run,
    )
    for install in installs:
        print(f"{install.status}: {install.name} -> {install.destination}")
    return 0


def install_skills(
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
                name=name,
                source=skill_source,
                destination=skill_dest,
                status=status,
            )
        )

    return installs


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


def _default_skills_dir() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home) / "skills"
    return Path.home() / ".codex" / "skills"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    raise SystemExit(main())
