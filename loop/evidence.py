"""Repository snapshots and atomic artifacts used by the verification runner."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class EvidenceError(RuntimeError):
    """A repository or artifact cannot be safely inspected."""


@dataclass(frozen=True)
class RepositorySnapshot:
    head: str | None
    files: dict[str, str]

    def to_json(self) -> dict[str, object]:
        return {"head": self.head, "files": self.files}

    @property
    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.to_json(), sort_keys=True).encode()).hexdigest()

    def changes_since(self, baseline: RepositorySnapshot) -> list[str]:
        return sorted(path for path in self.files.keys() | baseline.files.keys()
                      if self.files.get(path) != baseline.files.get(path))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_output(root: Path, args: list[str]) -> bytes:
    try:
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    except OSError as exc:
        raise EvidenceError(f"Git could not run in {root}: {exc}") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise EvidenceError(f"Git {' '.join(args)} failed in {root}: {detail}")
    return result.stdout


def require_git_root(root: Path) -> None:
    actual = Path(os.fsdecode(git_output(root, ["rev-parse", "--show-toplevel"])).strip()).resolve()
    if actual != root.resolve():
        raise EvidenceError(f"repository root must be the Git root {actual}, got {root}")


def repository_snapshot(root: Path, *, exclude: list[Path]) -> RepositorySnapshot:
    require_git_root(root)
    # An unborn repository has no HEAD, but is still a valid Git repository.
    try:
        head: str | None = git_output(root, ["rev-parse", "--verify", "HEAD^{commit}"]).decode().strip()
    except EvidenceError as exc:
        reference = git_output(root, ["symbolic-ref", "--quiet", "HEAD"]).decode().strip()
        exists = subprocess.run(["git", "show-ref", "--verify", "--quiet", reference], cwd=root, capture_output=True, check=False)
        if exists.returncode != 1:
            # An existing or corrupt ref is not an unborn branch. Preserve the error.
            raise exc
        head = None
    raw = git_output(root, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    exclusions = [item.absolute() for item in exclude]
    files: dict[str, str] = {}
    for name in sorted(set(os.fsdecode(raw).split("\0")) - {""}):
        path = root / name
        if any(path == item or item in path.parents for item in exclusions):
            continue
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            continue  # A deleted tracked path is absent from the current snapshot.
        if stat.S_ISLNK(metadata.st_mode):
            payload = "symlink:" + os.readlink(path)
        elif stat.S_ISREG(metadata.st_mode):
            payload = f"file:{stat.S_IMODE(metadata.st_mode)}:{file_sha256(path)}"
        elif stat.S_ISDIR(metadata.st_mode):
            # Git lists directories only for submodules. Include their complete state.
            payload = "submodule:" + repository_snapshot(path, exclude=[]).sha256
        else:
            raise EvidenceError(f"unsupported repository entry: {name}")
        files[name] = hashlib.sha256(os.fsencode(payload)).hexdigest()
    return RepositorySnapshot(head=head, files=files)


def parse_snapshot(value: object) -> RepositorySnapshot:
    if not isinstance(value, dict):
        raise EvidenceError("prepared baseline must be an object")
    head, files = value.get("head"), value.get("files")
    if head is not None and not isinstance(head, str):
        raise EvidenceError("baseline HEAD must be a string or null")
    if not isinstance(files, dict) or not all(
        isinstance(path, str) and isinstance(digest, str) for path, digest in files.items()
    ):
        raise EvidenceError("baseline file fingerprints must be a string mapping")
    return RepositorySnapshot(head=head, files=dict(files))


def read_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read artifact {path}: {exc}") from exc
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise EvidenceError(f"artifact {path} must be a JSON object")
    return payload


def atomic_json(path: Path, payload: object) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
