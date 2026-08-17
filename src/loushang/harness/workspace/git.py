"""Product-neutral Git workspace metadata discovery."""

from __future__ import annotations

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


__all__ = [
    "CommandResult",
    "GitPaths",
    "find_git_paths",
    "get_git_branch",
    "list_git_worktree_paths",
]
