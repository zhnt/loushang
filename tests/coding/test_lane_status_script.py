from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts/dev/lane_status.py"
SPEC = importlib.util.spec_from_file_location("lane_status", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
lane_status_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = lane_status_module
SPEC.loader.exec_module(lane_status_module)
collect_lane_statuses = lane_status_module.collect_lane_statuses
parse_worktree_porcelain = lane_status_module.parse_worktree_porcelain
render_lane_status = lane_status_module.render_lane_status


def test_parse_worktree_porcelain_keeps_branch_detached_and_prunable(tmp_path: Path) -> None:
    records = parse_worktree_porcelain(
        f"worktree {tmp_path / 'main'}\n"
        "HEAD abc\n"
        "branch refs/heads/main\n\n"
        f"worktree {tmp_path / 'detached'}\n"
        "HEAD def\n"
        "detached\n\n"
        f"worktree {tmp_path / 'stale'}\n"
        "HEAD 000\n"
        "prunable gitdir file points to non-existent location\n"
    )

    assert records[0].branch == "main"
    assert records[1].detached is True
    assert records[2].prunable == "gitdir file points to non-existent location"


def test_lane_status_is_read_only_and_reports_dirty_ahead_and_extra(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Lane Test")
    _git(repo, "config", "user.email", "lane@example.com")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".worktrees/\n", encoding="utf-8")
    _git(repo, "add", "README.md", ".gitignore")
    _git(repo, "commit", "-m", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    (repo / ".worktrees").mkdir()
    ai_lane = repo / ".worktrees" / "ai"
    extra = repo / ".worktrees" / "scratch"
    _git(repo, "worktree", "add", "-b", "task/ai", str(ai_lane), "main")
    (ai_lane / "ai.txt").write_text("committed\n", encoding="utf-8")
    _git(ai_lane, "add", "ai.txt")
    _git(ai_lane, "commit", "-m", "ai change")
    (ai_lane / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    _git(repo, "worktree", "add", "-b", "scratch", str(extra), "main")
    before = _git(repo, "status", "--porcelain").stdout

    statuses = collect_lane_statuses(repo)
    rendered = render_lane_status(statuses)

    after = _git(repo, "status", "--porcelain").stdout
    ai = next(status for status in statuses if status.name == "ai")
    residual = next(status for status in statuses if status.name == "extra")
    assert before == after
    assert ai.branch == "task/ai"
    assert ai.dirty is True
    assert ai.ahead == 1
    assert ai.behind == 0
    assert residual.path == extra.resolve()
    assert "Summary: active=3 dirty=1 behind=0 extra=1 prunable=0" in rendered
    assert "Lane status (read-only; compared with the local origin/main ref)" in rendered


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ("git", "-C", str(path), *args),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result
