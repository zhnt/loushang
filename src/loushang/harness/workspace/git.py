"""Product-neutral Git metadata and read-only workspace inventory observation."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    stdout: str = ""


@dataclass(frozen=True)
class GitPaths:
    repo_dir: Path
    common_git_dir: Path
    head_path: Path


CommandRunner = Callable[..., CommandResult]


def get_git_branch(
    cwd: str | Path,
    *,
    runner: CommandRunner | None = None,
) -> str | None:
    git_paths = find_git_paths(cwd)
    if git_paths is None:
        return None
    try:
        content = git_paths.head_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if content.startswith("ref: refs/heads/"):
        branch = content.removeprefix("ref: refs/heads/")
        if branch == ".invalid":
            return (
                _resolve_branch_with_git(git_paths.repo_dir, runner=runner)
                or "detached"
            )
        return branch
    return "detached"


def find_git_paths(cwd: str | Path) -> GitPaths | None:
    current = Path(cwd).resolve()
    while True:
        git_path = current / ".git"
        if git_path.exists():
            paths = _paths_from_git_path(current, git_path)
            if paths is not None:
                return paths
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _paths_from_git_path(repo_dir: Path, git_path: Path) -> GitPaths | None:
    try:
        if git_path.is_file():
            content = git_path.read_text(encoding="utf-8").strip()
            if not content.startswith("gitdir: "):
                return None
            git_dir = (repo_dir / content[8:].strip()).resolve()
            head_path = git_dir / "HEAD"
            if not head_path.exists():
                return None
            common_dir_path = git_dir / "commondir"
            common_git_dir = (
                (
                    git_dir / common_dir_path.read_text(encoding="utf-8").strip()
                ).resolve()
                if common_dir_path.exists()
                else git_dir
            )
            return GitPaths(
                repo_dir=repo_dir,
                common_git_dir=common_git_dir,
                head_path=head_path,
            )
        if git_path.is_dir():
            head_path = git_path / "HEAD"
            if not head_path.exists():
                return None
            return GitPaths(
                repo_dir=repo_dir,
                common_git_dir=git_path,
                head_path=head_path,
            )
    except OSError:
        return None
    return None


def list_git_worktree_paths(
    cwd: str | Path,
    *,
    runner: CommandRunner | None = None,
) -> tuple[Path, ...]:
    """List canonical worktree roots for the repository containing ``cwd``."""

    git_paths = find_git_paths(cwd)
    if git_paths is None:
        return ()
    command_runner = _run_command if runner is None else runner
    result = command_runner(
        "git",
        ("--no-optional-locks", "worktree", "list", "--porcelain"),
        cwd=git_paths.repo_dir,
    )
    if not result.ok:
        return (git_paths.repo_dir,)
    roots: list[Path] = []
    for line in result.stdout.splitlines():
        if not line.startswith("worktree "):
            continue
        root = Path(line.removeprefix("worktree ").strip()).resolve(strict=False)
        if root not in roots:
            roots.append(root)
    return tuple(roots) or (git_paths.repo_dir,)


def _resolve_branch_with_git(
    repo_dir: Path,
    *,
    runner: CommandRunner | None = None,
) -> str | None:
    command_runner = _run_command if runner is None else runner
    result = command_runner(
        "git",
        ("--no-optional-locks", "symbolic-ref", "--quiet", "--short", "HEAD"),
        cwd=repo_dir,
    )
    branch = result.stdout.strip() if result.ok else ""
    return branch or None


def _run_command(
    command: str,
    args: tuple[str, ...],
    *,
    cwd: Path,
) -> CommandResult:
    try:
        result = subprocess.run(
            [command, *args],
            cwd=cwd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return CommandResult(ok=False)
    return CommandResult(ok=result.returncode == 0, stdout=result.stdout)


def observe_workspace_inventory(
    root: Path,
    *,
    max_files: int,
    max_bytes: int,
    ignored_directories: frozenset[str],
    error_type: type[Exception],
    submodule_error: str,
    file_limit_error: str,
    external_link_error: str,
    byte_limit_error: str,
) -> dict[str, str]:
    """Observe bounded staged Git names or an ordered fallback tree, read-only.

    Git launch/timeout errors propagate. A nonzero Git result alone falls back;
    this is an observation, with the original path-based races, not a snapshot.
    """
    query = subprocess.run(
        [
            "git",
            "-c",
            "core.fsmonitor=false",
            "ls-files",
            "-z",
            "--stage",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        cwd=root,
        capture_output=True,
        timeout=2,
    )
    names: list[str]
    if query.returncode == 0:
        selected_names: set[str] = set()
        for entry in query.stdout.split(b"\0"):
            if not entry:
                continue
            header, separator, raw_name = entry.partition(b"\t")
            if separator and re.fullmatch(rb"[0-7]{6} [0-9a-f]{40,64} [0-3]", header):
                if header.startswith(b"160000 "):
                    raise error_type(submodule_error)
                selected_names.add(os.fsdecode(raw_name))
            else:
                selected_names.add(os.fsdecode(entry))
        names = sorted(selected_names)
    else:
        names = []
        for parent, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if d not in ignored_directories]
            names.extend(
                (Path(parent) / name).relative_to(root).as_posix() for name in files
            )
            if len(names) > max_files:
                raise error_type(file_limit_error)
    if len(names) > max_files:
        raise error_type(file_limit_error)
    result, size = {}, 0
    for name in names:
        path = root / name
        if not path.resolve().is_relative_to(root):
            raise error_type(external_link_error)
        if path.is_symlink():
            result[name] = "symlink:" + os.readlink(path)
        elif path.is_file():
            size += path.stat().st_size
            if size > max_bytes:
                raise error_type(byte_limit_error)
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            result[name] = "missing"
    return result


def observe_git_inventory(root: Path) -> dict[str, str]:
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
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            result[name] = "missing"
    return result


__all__ = [
    "CommandResult",
    "GitPaths",
    "find_git_paths",
    "get_git_branch",
    "list_git_worktree_paths",
    "observe_git_inventory",
    "observe_workspace_inventory",
]
