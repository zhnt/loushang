from __future__ import annotations

from pathlib import Path

from loushang.harness.workspace.git import (
    CommandResult,
    get_git_branch,
    list_git_worktree_paths,
)


def test_git_branch_handles_invalid_reftable_head_via_git_fallback(
    tmp_path: Path,
) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text(
        "ref: refs/heads/.invalid\n",
        encoding="utf-8",
    )

    def runner(
        command: str,
        args: tuple[str, ...],
        *,
        cwd: Path,
        **kwargs: object,
    ) -> CommandResult:
        assert command == "git"
        assert args == (
            "--no-optional-locks",
            "symbolic-ref",
            "--quiet",
            "--short",
            "HEAD",
        )
        assert cwd == tmp_path
        return CommandResult(ok=True, stdout="main")

    assert get_git_branch(tmp_path, runner=runner) == "main"


def test_git_branch_returns_detached_when_branch_cannot_be_resolved(
    tmp_path: Path,
) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text(
        "ref: refs/heads/.invalid\n",
        encoding="utf-8",
    )

    def runner(
        command: str,
        args: tuple[str, ...],
        *,
        cwd: Path,
        **kwargs: object,
    ) -> CommandResult:
        return CommandResult(ok=False)

    assert get_git_branch(tmp_path, runner=runner) == "detached"


def test_git_metadata_is_owned_by_harness_workspace() -> None:
    assert CommandResult.__module__ == "loushang.harness.workspace.git"
    assert get_git_branch.__module__ == "loushang.harness.workspace.git"


def test_list_git_worktree_paths_parses_porcelain_output(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    other = tmp_path.parent / "other-worktree"

    def runner(
        command: str,
        args: tuple[str, ...],
        *,
        cwd: Path,
        **kwargs: object,
    ) -> CommandResult:
        assert command == "git"
        assert args == (
            "--no-optional-locks",
            "worktree",
            "list",
            "--porcelain",
        )
        assert cwd == tmp_path
        return CommandResult(
            ok=True,
            stdout=f"worktree {tmp_path}\nHEAD abc\n\nworktree {other}\nHEAD def\n",
        )

    assert list_git_worktree_paths(tmp_path, runner=runner) == (
        tmp_path.resolve(),
        other.resolve(),
    )
