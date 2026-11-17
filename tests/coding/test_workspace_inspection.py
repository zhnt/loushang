import shutil
import subprocess

import pytest

from loushang.coding.workspace_inspection import inspect_workspace


def test_reports_project_toolchain_without_git(tmp_path):
    (tmp_path / "go.mod").write_text("module workspace\n\ngo 1.24\n", encoding="utf-8")
    report = inspect_workspace(tmp_path)
    assert report["git"] is None
    assert report["toolchains"] == [{"name": "Go", "declared": "1.24"}]
    assert report["changes"] == []


@pytest.mark.skipif(shutil.which("git") is None, reason="Git is required")
def test_linked_worktree_separates_staged_unstaged_and_untracked(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args, cwd=repo):
        subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)

    git("init")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "Initial")
    worktree = tmp_path / "linked"
    git("worktree", "add", "-b", "review", str(worktree))

    file = worktree / "index.html"
    file.write_text("staged\n", encoding="utf-8")
    git("add", "index.html", cwd=worktree)
    file.write_text("revised\n", encoding="utf-8")
    (worktree / "notes.txt").write_text("one\ntwo\n", encoding="utf-8")

    report = inspect_workspace(worktree.resolve())
    assert report["git"]["branch"] == "review"
    assert report["git"]["worktree"] == "linked"
    assert len(report["git"]["commit"]) >= 40
    assert report["changes"] == [
        {"path": "index.html", "kind": "staged", "added": 1, "removed": 0},
        {"path": "index.html", "kind": "unstaged", "added": 1, "removed": 1},
        {"path": "notes.txt", "kind": "untracked", "added": 2, "removed": 0},
    ]
    assert "+revised" in report["unstagedDiff"]


def test_non_git_review_only_includes_successful_workspace_file_operations(tmp_path):
    from loushang.ai.types import ToolResultMessage
    from loushang.coding.workspace_inspection import inspect_session_changes

    def result(tool, path, details, *, failed=False):
        return ToolResultMessage("toolResult", "call", tool, [], failed, 1.0, {
            "path": str(path), **details,
        })

    edited = tmp_path / "old.txt"
    patch = f"--- {edited}\n+++ {edited}\n@@ -1 +1,2 @@\n-old\n+new\n+more\n"
    report = inspect_session_changes(tmp_path, [
        result("edit", edited, {"diff": patch}),
        result("write", tmp_path / "index.html", {"operation": "create"}),
        result("write", tmp_path / "error.txt", {"operation": "create"}, failed=True),
        result("edit", tmp_path.parent / "outside.txt", {"diff": patch}),
    ])

    assert report["sessionChanges"] == [
        {"path": "old.txt", "created": False, "added": 2, "removed": 1},
        {"path": "index.html", "created": True, "added": None, "removed": None},
    ]
    assert report["sessionDiff"] == "--- old.txt\n+++ old.txt\n@@ -1 +1,2 @@\n-old\n+new\n+more\n"
