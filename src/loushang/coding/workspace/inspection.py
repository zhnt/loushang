"""On-demand inspection of a registered Coding workspace."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from loushang.ai.types import ToolResultMessage
from loushang.harness.workspace.git import CommandResult, find_git_paths, get_git_branch


def _text(path: Path, limit: int = 64 * 1024) -> str:
    try:
        if path.is_symlink() or not path.is_file():
            return ""
        with path.open("rb") as file:
            data = file.read(limit + 1)
        return data.decode("utf-8") if len(data) <= limit and b"\0" not in data else ""
    except (OSError, UnicodeError):
        return ""


def _git(root: Path, deadline: float, *args: str) -> str | None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        with tempfile.TemporaryFile() as output:
            subprocess.run(
                ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root), *args],
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
                timeout=min(3, remaining), check=True, env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            output.seek(0)
            data = output.read(256 * 1024 + 1)
    except (OSError, subprocess.SubprocessError):
        return None
    return data.decode("utf-8", errors="replace") if len(data) <= 256 * 1024 else None


def _toolchains(root: Path) -> list[dict[str, str]]:
    tools = []
    python = _text(root / "pyproject.toml")
    venv = root / ".venv"
    config = "" if venv.is_symlink() else _text(venv / "pyvenv.cfg")
    python_version = _text(root / ".python-version").strip()
    if python or config or python_version or (root / "requirements.txt").is_file():
        try:
            requirement = tomllib.loads(python).get("project", {}).get("requires-python", "")
        except (AttributeError, ValueError):
            requirement = ""
        version = next((line.partition("=")[2].strip() for line in config.splitlines()
                        if line.partition("=")[0].strip() == "version"), "")
        tools.append({"name": "Python", "declared": str(requirement or python_version)[:120],
                      "detected": version[:120], "environment": ".venv" if config else ""})
    package = _text(root / "package.json")
    node_version = (_text(root / ".node-version") or _text(root / ".nvmrc")).strip()
    if package or node_version:
        try:
            node = json.loads(package).get("engines", {}).get("node", "")
        except (AttributeError, ValueError):
            node = ""
        tools.append({"name": "Node.js", "declared": str(node or node_version)[:120]})
    module = _text(root / "go.mod")
    if module:
        version = next((line[3:].strip() for line in module.splitlines() if line.startswith("go ")), "")
        tools.append({"name": "Go", "declared": version[:120]})
    maven = _text(root / "pom.xml")
    if maven or any((root / item).is_file() for item in ("build.gradle", "build.gradle.kts")):
        java = _text(root / ".java-version").strip()
        if not java:
            release = re.search(r"<(maven\.compiler\.release|java\.version)>\s*([\w.-]+)\s*</\1>", maven)
            java = release[2] if release else ""
        tools.append({"name": "Java", "declared": java[:120]})
    return tools


def inspect_workspace(root: Path) -> dict[str, Any]:
    report: dict[str, Any] = {"toolchains": _toolchains(root), "git": None, "changes": [], "limited": False}
    deadline = time.monotonic() + 5

    def git_branch_runner(_command: str, args: tuple[str, ...], *, cwd: Path) -> CommandResult:
        result = _git(cwd, deadline, *args)
        return CommandResult(result is not None, result or "")

    try:
        location = find_git_paths(root)
        if location is None:
            return report
        branch = get_git_branch(root, runner=git_branch_runner)
    except (OSError, UnicodeError, RuntimeError):
        report["limited"] = True
        return report
    report["git"] = {
        "root": str(location.repo_dir)[:4096],
        "branch": (branch or "")[:512] if branch != "detached" else "",
        "commit": (_git(root, deadline, "rev-parse", "--verify", "HEAD") or "").strip()[:64],
        "worktree": location.repo_dir.name[:256] if location.head_path.parent != location.common_git_dir else "",
    }
    for kind, args in (("staged", ("--cached",)), ("unstaged", ())):
        stats = _git(root, deadline, "diff", *args, "--no-ext-diff", "--no-textconv", "--no-renames", "--relative", "--numstat", "-z", "--", ".")
        if stats is None:
            report["limited"] = True
            continue
        for row in stats.split("\0"):
            if not row:
                continue
            fields = row.split("\t", 2)
            if len(fields) != 3:
                report["limited"] = True
                continue
            added, removed, path = fields
            _add_change(report, path, kind, added, removed)
        diff = _git(root, deadline, "diff", *args, "--no-ext-diff", "--no-textconv",
                    "--no-renames", "--relative", "--no-color", "--", ".")
        if diff is None:
            report["limited"] = True
        elif diff:
            report[kind + "Diff"] = diff.encode()[:4500].decode(errors="ignore")
            report["limited"] |= len(diff.encode()) > 4500
    untracked = _git(root, deadline, "ls-files", "--others", "--exclude-standard", "-z", "--", ".")
    if untracked is None:
        report["limited"] = True
    for path in (untracked or "").split("\0"):
        if not path:
            continue
        if len(report["changes"]) >= 60:
            report["limited"] = True
            break
        candidate = root / path
        try:
            text = _text(candidate) if candidate.resolve().is_relative_to(root) else ""
        except (OSError, RuntimeError):
            text = ""
        _add_change(report, path, "untracked", str(len(text.splitlines())) if text else "-", "0")
    return report


def _add_change(report: dict[str, Any], path: str, kind: str, added: str, removed: str) -> None:
    if len(report["changes"]) >= 60 or len(json.dumps(path, ensure_ascii=False).encode()) > 320:
        report["limited"] = True
        return
    report["changes"].append({"path": path, "kind": kind,
                              "added": int(added) if added.isdecimal() else None,
                              "removed": int(removed) if removed.isdecimal() else None})


def inspect_session_changes(root: Path, messages: Iterable[object]) -> dict[str, object]:
    """Summarize recorded tool effects when the project has no Git baseline."""
    files: dict[str, dict[str, object]] = {}
    patches: list[str] = []
    remaining = 4500
    limited = False
    for message in messages:
        if not isinstance(message, ToolResultMessage) or message.is_error:
            continue
        if message.tool_name not in {"write", "edit"} or not isinstance(message.details, dict):
            continue
        path = message.details.get("path")
        if not isinstance(path, str):
            continue
        relative = Path(path)
        if not relative.is_absolute() or ".." in relative.parts or not relative.is_relative_to(root):
            continue
        name = relative.relative_to(root).as_posix()
        if len(json.dumps(name, ensure_ascii=False).encode()) > 320 or (name not in files and len(files) >= 60):
            limited = True
            continue
        patch = message.details.get("diff")
        operation = message.details.get("operation")
        item = files.setdefault(name, {"path": name, "added": 0, "removed": 0, "created": operation == "create"})
        if not isinstance(patch, str) or not patch:
            item["added"] = item["removed"] = None
            continue
        lines = patch.splitlines()
        for key, prefix in (("added", "+"), ("removed", "-")):
            count = item[key]
            if isinstance(count, int):
                item[key] = count + sum(line.startswith(prefix) for line in lines[2:])
        rendered = ("\n".join([f"--- {name}", f"+++ {name}", *lines[2:]]) + "\n").encode()
        if remaining > 0:
            patches.append(rendered[:remaining].decode(errors="ignore"))
        limited |= len(rendered) > remaining
        remaining = max(0, remaining - len(rendered))
    return {"sessionChanges": list(files.values()), "sessionDiff": "".join(patches), "limited": limited}
