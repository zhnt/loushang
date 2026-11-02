"""Strict server admission and checked material reads for the hosted profile only."""

from __future__ import annotations

import json
import math
import stat
from pathlib import Path
from types import MappingProxyType

from loushang.harnesswork.goal import GoalError, Requirement

from ._goal_repository_task import RepositoryTask, digest


def member(root, name, *, directory=False):
    if not isinstance(name, str) or not name or name.startswith("-"):
        raise GoalError("invalid task member")
    relative = Path(name)
    if (
        relative.is_absolute()
        or relative.as_posix() != name
        or any(part in ("", ".", "..") for part in name.split("/"))
    ):
        raise GoalError("invalid task member")
    path = root
    for part in relative.parts:
        path /= part
        if path.is_symlink():
            raise GoalError("symlink task member")
    if not path.resolve().is_relative_to(root):
        raise GoalError("task member outside root")
    info = path.stat()
    if directory and stat.S_ISDIR(info.st_mode):
        return path
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_size > 1024 * 1024
    ):
        raise GoalError("task member is not a bounded single-link file")
    return path


class HostedRepositoryTask(RepositoryTask):
    def __init__(self, manifest, expected_digest):
        self.path = manifest.resolve()
        self.digest = expected_digest
        raw = self.path.read_bytes()
        if digest(raw) != expected_digest:
            raise GoalError("task manifest changed")
        config = json.loads(raw)
        if (
            type(config.get("version")) is not int
            or config["version"] != 1
            or config.get("accepted") is not True
        ):
            raise GoalError("repository task package is not accepted")
        rows = config["requirements"]
        if len(rows) != 6 or {r["id"] for r in rows} != {
            f"RC-0{i}" for i in range(1, 7)
        }:
            raise GoalError("hosted task requires unique RC-01 through RC-06")
        if any(not isinstance(r["text"], str) or not r["text"].strip() for r in rows):
            raise GoalError("invalid requirement text")
        budget = config.get("closeout_budget")
        if (
            not isinstance(budget, dict)
            or set(budget) != {"version", "work_intents", "planning_intents"}
            or any(
                type(budget[k]) is not int or not 1 <= budget[k] <= maximum
                for k, maximum in (
                    ("version", 1),
                    ("work_intents", 6),
                    ("planning_intents", 2),
                )
            )
        ):
            raise GoalError("hosted task requires closeout budget")
        self._config_bytes = raw
        if any(not Path(config[k]).is_absolute() for k in ("workspace", "temporary_root", "python")):
            raise GoalError("explicit absolute task roots and interpreter required")
        self.root = Path(config["workspace"]).resolve()
        for key in ("allowed_files", "read_files"):
            if not isinstance(config[key], list) or any(
                not isinstance(n, str) for n in config[key]
            ):
                raise GoalError("invalid file set")
        inspections = config["inspect_files"]
        selectors = config["check_selectors"]
        if not isinstance(inspections, dict) or set(inspections) != {
            "reader",
            "operations",
            "tests",
        }:
            raise GoalError("missing required inspect groups")
        if not isinstance(selectors, dict) or "regression" not in selectors:
            raise GoalError("missing full verification selectors")
        for group in (*inspections.values(), *selectors.values()):
            if (
                not isinstance(group, list)
                or not group
                or any(not isinstance(n, str) for n in group)
            ):
                raise GoalError("invalid task group")
        timeout = config["check_timeout_seconds"]
        if (
            type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise GoalError("invalid check timeout")
        self.allowed, self.readable = (
            tuple(config["allowed_files"]),
            tuple(config["read_files"]),
        )
        if (
            not self.allowed
            or len(set(self.allowed)) != len(self.allowed)
            or len(set(self.readable)) != len(self.readable)
        ):
            raise GoalError("invalid file set")
        if (
            not set(self.allowed)
            <= set(self.readable)
            <= set(config["workspace_start"])
        ):
            raise GoalError("file sets outside frozen scope")
        if any(
            not set(group) <= set(self.readable)
            for group in config["inspect_files"].values()
        ):
            raise GoalError("inspect outside read scope")
        self.requirements = tuple(Requirement(r["id"], r["text"]) for r in rows)
        self.verify()
        self.snapshot()
        self.initial = MappingProxyType(
            self.read_files(self.allowed, config["workspace_start"])
        )

    @property
    def config(self):
        # External mutation of a returned dict cannot change the frozen contract.
        return json.loads(self._config_bytes)

    def verify(self):
        if self.path.read_bytes() != self._config_bytes:
            raise GoalError("task manifest changed")
        config = self.config
        protected = config["protected"]
        if not {"method.json", "driver.py", "test_contract.py"} <= set(protected):
            raise GoalError("missing mandatory protected inputs")
        for name, expected in protected.items():
            if digest(member(self.path.parent, name).read_bytes()) != expected:
                raise GoalError("protected task input changed")
        physical = set()
        for name in self.readable:
            info = member(self.root, name).stat()
            identity = (info.st_dev, info.st_ino)
            if identity in physical:
                raise GoalError("duplicate physical file")
            physical.add(identity)
        for group in config["check_selectors"].values():
            if not isinstance(group, list) or not group:
                raise GoalError("invalid check selectors")
            for name in group:
                member(self.root, name, directory=True)

    def read_files(self, names, snapshot):
        self.verify()
        result = {}
        baseline = self.config["workspace_start"]
        for name in names:
            if name not in self.readable:
                raise GoalError("material outside read scope")
            data = member(self.root, name).read_bytes()
            expected = snapshot[name] if name in self.allowed else baseline[name]
            if digest(data) != expected:
                raise GoalError("material changed during read")
            result[name] = data.decode("utf-8")
        self.verify()
        if self.snapshot() != {n: snapshot[n] for n in self.allowed}:
            raise GoalError("candidate changed during material read")
        return result

    def material(self):
        return {
            "acceptance": self.config["requirements"],
            "allowed_files": self.allowed,
            "files": self.read_files(self.readable, self.snapshot()),
        }
