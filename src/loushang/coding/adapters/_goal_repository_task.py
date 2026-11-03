"""Private, frozen local repository task inputs; no scheduler or model calls."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

from loushang.harnesswork.goal import GoalError, Requirement


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def inventory(root: Path) -> dict[str, str]:
    """Include tracked and nonignored new files, preserving symlink identity."""
    names = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
        )
        .decode()
        .split("\0")
    )
    result = {}
    for name in sorted(set(names) - {""}):
        path = root / name
        if path.is_symlink():
            result[name] = "symlink:" + os.readlink(path)
        elif path.is_file():
            result[name] = digest(path.read_bytes())
        else:
            result[name] = "missing"
    return result


class RepositoryTask:
    """An explicitly selected accepted package, never discovered from model text."""

    policy_id = "coding-repository-review/v1"

    def __init__(self, manifest: Path, expected_digest: str):
        self.path = manifest.resolve()
        self.digest = expected_digest
        self.verify()
        self.config = json.loads(self.path.read_bytes())
        if (
            type(self.config.get("version")) is not int
            or self.config["version"] != 1
            or self.config.get("accepted") is not True
        ):
            raise GoalError("repository task package is not accepted")
        self.root = Path(self.config["workspace"]).resolve()
        self.allowed = tuple(self.config["allowed_files"])
        self.readable = tuple(self.config["read_files"])
        if not set(self.allowed) <= set(self.readable):
            raise GoalError("write scope must be readable")
        for name in self.readable:
            path = Path(name)
            if path.is_absolute() or ".." in path.parts or not name:
                raise GoalError("invalid task file scope")
        self.requirements = tuple(
            Requirement(row["id"], row["text"]) for row in self.config["requirements"]
        )

    def verify(self):
        if digest(self.path.read_bytes()) != self.digest:
            raise GoalError("task manifest changed")
        config = json.loads(self.path.read_bytes())
        for name, expected in config["protected"].items():
            path = self.path.parent / name
            if (
                Path(name).is_absolute()
                or ".." in Path(name).parts
                or path.is_symlink()
            ):
                raise GoalError("invalid protected task path")
            if digest(path.read_bytes()) != expected:
                raise GoalError("protected task input changed")

    def snapshot(self):
        self.verify()
        current = inventory(self.root)
        baseline = self.config["workspace_start"]
        if set(current) != set(baseline):
            raise GoalError("repository file set changed")
        if any(
            current[name] != value
            for name, value in baseline.items()
            if name not in self.allowed
        ):
            raise GoalError("protected repository file changed")
        for name in self.allowed:
            info = (self.root / name).lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_size > 1024 * 1024
            ):
                raise GoalError("task target is not a bounded regular file")
        return {name: current[name] for name in self.allowed}

    def material(self):
        return {
            "acceptance": self.config["requirements"],
            "allowed_files": self.allowed,
            "files": self.read_files(self.readable, None),
        }

    def read_files(self, names, snapshot):
        return {name: (self.root / name).read_text() for name in names}
