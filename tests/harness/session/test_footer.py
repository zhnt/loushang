from __future__ import annotations

import time
from pathlib import Path


def test_footer_data_provider_caches_and_refreshes_git_branch(tmp_path) -> None:
    from loushang.harness.session.footer import FooterDataProvider

    branch = {"value": "main"}
    resolver_calls: list[Path] = []

    def branch_resolver(cwd: str | Path) -> str | None:
        resolver_calls.append(Path(cwd))
        return branch["value"]

    provider = FooterDataProvider(tmp_path, branch_resolver=branch_resolver)
    changes: list[str | None] = []
    unsubscribe = provider.on_branch_change(changes.append)

    assert provider.get_git_branch() == "main"
    assert provider.get_git_branch() == "main"
    assert resolver_calls == [tmp_path]

    branch["value"] = "feature"
    assert provider.get_git_branch() == "main"
    assert provider.refresh_git_branch() == "feature"
    assert changes == ["feature"]

    unsubscribe()
    branch["value"] = "release"
    assert provider.refresh_git_branch() == "release"
    assert changes == ["feature"]


def test_footer_data_provider_set_cwd_invalidates_branch_and_notifies(tmp_path) -> None:
    from loushang.harness.session.footer import FooterDataProvider

    cwd_a = tmp_path / "a"
    cwd_b = tmp_path / "b"
    cwd_a.mkdir()
    cwd_b.mkdir()
    branches = {cwd_a: "main", cwd_b: "worktree"}

    def branch_resolver(cwd: str | Path) -> str | None:
        return branches[Path(cwd)]

    provider = FooterDataProvider(cwd_a, branch_resolver=branch_resolver)
    changes: list[str | None] = []
    provider.on_branch_change(changes.append)

    assert provider.get_git_branch() == "main"
    provider.set_cwd(cwd_b)

    assert provider.cwd == cwd_b
    assert provider.get_git_branch() == "worktree"
    assert changes == ["worktree"]


def test_footer_data_provider_snapshot_statuses_and_provider_count(tmp_path) -> None:
    from loushang.harness.session.footer import FooterDataProvider

    provider = FooterDataProvider(tmp_path, branch_resolver=lambda cwd: "main")

    provider.set_extension_status("python", "ready")
    provider.set_extension_status("node", "loading")
    provider.set_extension_status("node", None)
    provider.set_available_provider_count(3)

    snapshot = provider.snapshot()
    assert snapshot.git_branch == "main"
    assert snapshot.extension_statuses == {"python": "ready"}
    assert snapshot.available_provider_count == 3

    snapshot.extension_statuses["python"] = "mutated"
    assert provider.get_extension_statuses() == {"python": "ready"}

    provider.clear_extension_statuses()
    assert provider.snapshot().extension_statuses == {}
    assert provider.snapshot().available_provider_count == 3


def test_footer_data_provider_defaults_provider_count_to_zero(tmp_path) -> None:
    from loushang.harness.session.footer import FooterDataProvider

    provider = FooterDataProvider(tmp_path, branch_resolver=lambda cwd: None)

    assert provider.get_available_provider_count() == 0
    assert provider.snapshot().available_provider_count == 0


def test_footer_data_provider_git_watcher_refreshes_branch_on_head_change(tmp_path) -> None:
    from loushang.harness.session.footer import FooterDataProvider

    repo = tmp_path / "repo"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    provider = FooterDataProvider(repo)
    changes: list[str | None] = []
    provider.on_branch_change(changes.append)
    provider.start_git_watcher(poll_interval_seconds=0.01, debounce_seconds=0.01)

    assert provider.get_git_branch() == "main"
    (git_dir / "HEAD").write_text("ref: refs/heads/feature\n", encoding="utf-8")

    deadline = time.monotonic() + 2
    while not changes and time.monotonic() < deadline:
        time.sleep(0.02)

    provider.dispose()
    assert changes == ["feature"]


def test_footer_data_provider_git_watcher_restarts_when_cwd_changes(tmp_path) -> None:
    from loushang.harness.session.footer import FooterDataProvider

    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    for repo, branch in ((repo_a, "main"), (repo_b, "work")):
        git_dir = repo / ".git"
        git_dir.mkdir(parents=True)
        (git_dir / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")

    provider = FooterDataProvider(repo_a)
    changes: list[str | None] = []
    provider.on_branch_change(changes.append)
    provider.start_git_watcher(poll_interval_seconds=0.01, debounce_seconds=0.01)

    assert provider.get_git_branch() == "main"
    provider.set_cwd(repo_b)
    assert provider.get_git_branch() == "work"

    (repo_b / ".git" / "HEAD").write_text("ref: refs/heads/release\n", encoding="utf-8")
    deadline = time.monotonic() + 2
    while changes[-1:] != ["release"] and time.monotonic() < deadline:
        time.sleep(0.02)

    provider.dispose()
    assert changes == ["work", "release"]
