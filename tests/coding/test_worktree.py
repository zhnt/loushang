from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from loushang.coding.worktree import (
    CodingGitWorktreeLeasePort,
    create_coding_git_workspace_manager,
)
from loushang.harness.multiagent import (
    AgentPath,
    AgentRef,
    WorkspaceLeaseRequest,
)
from loushang.harness.workspace import GitWorkspaceError
from loushang.harness.workspace.exec import ExecRequest, ExecResult, ExecService


def _request() -> WorkspaceLeaseRequest:
    return WorkspaceLeaseRequest(
        agent_ref=AgentRef(AgentPath.root().child("worker"), 1),
        agent_type="implementation_worker",
        mode="isolated",
    )


async def _git(service: ExecService, cwd: Path, *args: str) -> ExecResult:
    result = await service.execute(
        ExecRequest(command=("git", *args), cwd=str(cwd))
    )
    assert result.exit_code == 0, result.stderr
    return result


async def _repository(path: Path) -> ExecService:
    path.mkdir()
    service = ExecService()
    await _git(service, path, "init")
    await _git(service, path, "config", "user.email", "multiagent@example.invalid")
    await _git(service, path, "config", "user.name", "Multi Agent Test")
    (path / "README.md").write_text("base\n", encoding="utf-8")
    await _git(service, path, "add", "README.md")
    await _git(service, path, "commit", "-m", "initial")
    return service


def _port(
    repo: Path,
    tmp_path: Path,
    service: ExecService,
    *,
    nonce: str,
) -> CodingGitWorktreeLeasePort:
    return CodingGitWorktreeLeasePort(
        cwd=repo,
        exec_service=service,
        state_root=tmp_path / "state",
        lease_root=tmp_path / "checkouts",
        uuid_factory=lambda: nonce,
    )


def test_unchanged_detached_worktree_is_removed_without_a_branch(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repo = tmp_path / "repo"
        service = await _repository(repo)
        port = _port(repo, tmp_path, service, nonce="clean")

        lease = await port.acquire(_request())
        worktree = Path(lease.execution_ref)
        record = port.manager.get(lease.workspace_ref)

        assert record.status == "active"
        assert record.base_oid
        assert worktree.is_dir()
        symbolic = await service.execute(
            ExecRequest(
                command=("git", "symbolic-ref", "--quiet", "HEAD"),
                cwd=str(worktree),
            )
        )
        assert symbolic.exit_code != 0

        snapshot = await port.snapshot(lease)
        released = await port.release(lease)

        assert snapshot.changed is False
        assert snapshot.artifact_refs == ()
        assert released.workspace_ref is None
        assert worktree.exists() is False
        assert port.manager.get(lease.workspace_ref).status == "discarded"

    asyncio.run(scenario())


def test_changed_worktree_captures_applies_and_discards_an_immutable_artifact(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repo = tmp_path / "repo"
        service = await _repository(repo)
        port = _port(repo, tmp_path, service, nonce="changed")

        lease = await port.acquire(_request())
        worktree = Path(lease.execution_ref)
        (worktree / "README.md").write_text("changed\n", encoding="utf-8")
        (worktree / "result.bin").write_bytes(b"\x00agent-output\xff")

        snapshot = await port.snapshot(lease)
        assert snapshot.changed is True
        assert snapshot.change_set_ref is None
        assert len(snapshot.artifact_refs) == 1
        assert snapshot.artifact_refs[0].startswith("git-artifact:")
        assert "result.bin" in port.manager.artifact_diff(lease.workspace_ref)

        released = await port.release(lease)
        record = port.manager.get(lease.workspace_ref)
        assert released.retained is True
        assert released.artifact_refs == record.artifact_refs
        assert record.status == "retained"
        assert record.runtime_owned is False
        assert worktree.is_dir()

        plan = await port.manager.plan_apply_workspace(
            lease.workspace_ref,
            target=repo,
        )
        applied = await port.manager.apply(plan)
        assert applied.applied is True
        assert (repo / "README.md").read_text(encoding="utf-8") == "changed\n"
        assert (repo / "result.bin").read_bytes() == b"\x00agent-output\xff"
        assert applied.record.status == "applied"

        discarded = await port.manager.discard(lease.workspace_ref)
        assert discarded.discarded is True
        assert discarded.record.status == "discarded"
        assert worktree.exists() is False
        assert port.manager.artifact_diff(lease.workspace_ref)

    asyncio.run(scenario())


@pytest.mark.skipif(
    sys.platform == "darwin",
    reason="macOS env-sensitive golden/smoke; may hide a real macOS product bug — tracked separately as issue #455",
)
def test_capture_failure_preserves_the_workspace_and_model_result_channel(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repo = tmp_path / "repo"
        service = await _repository(repo)
        port = _port(repo, tmp_path, service, nonce="inspect")

        lease = await port.acquire(_request())
        worktree = Path(lease.execution_ref)
        await _git(service, repo, "worktree", "remove", "--force", str(worktree))

        snapshot = await port.snapshot(lease)
        record = port.manager.get(lease.workspace_ref)

        assert snapshot.workspace_ref == lease.workspace_ref
        assert snapshot.artifact_refs == ()
        assert snapshot.changed is True
        assert snapshot.retained is True
        assert record.status == "needs_inspection"
        assert record.last_error

        released = await port.release(lease)
        assert released.workspace_ref == lease.workspace_ref
        assert port.manager.get(lease.workspace_ref).runtime_owned is False

    asyncio.run(scenario())


def test_apply_rejects_touched_target_dirt_and_artifact_tampering(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repo = tmp_path / "repo"
        service = await _repository(repo)
        port = _port(repo, tmp_path, service, nonce="tamper")
        lease = await port.acquire(_request())
        worktree = Path(lease.execution_ref)
        (worktree / "README.md").write_text("worker\n", encoding="utf-8")
        snapshot = await port.snapshot(lease)
        await port.release(lease)

        (repo / "README.md").write_text("parent\n", encoding="utf-8")
        with pytest.raises(GitWorkspaceError, match="artifact path"):
            await port.manager.plan_apply_workspace(lease.workspace_ref, target=repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")

        artifact_ref = snapshot.artifact_refs[0]
        descriptor_digest = artifact_ref.rsplit(":", 1)[-1]
        descriptor_path = (
            tmp_path
            / "state"
            / "workspaces"
            / port.manager.repository_id
            / "descriptors"
            / f"{descriptor_digest}.json"
        )
        descriptor_path.write_text("{}\n", encoding="utf-8")
        with pytest.raises(GitWorkspaceError, match="descriptor digest mismatch"):
            await port.manager.plan_apply_workspace(lease.workspace_ref, target=repo)

    asyncio.run(scenario())


def test_managed_roots_must_not_overlap_a_registered_worktree(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repo = tmp_path / "repo"
        service = await _repository(repo)
        port = CodingGitWorktreeLeasePort(
            cwd=repo,
            exec_service=service,
            state_root=repo / ".loushang" / "state",
            lease_root=repo / ".loushang" / "worktrees",
        )

        with pytest.raises(GitWorkspaceError, match="overlaps"):
            await port.acquire(_request())

    asyncio.run(scenario())


def test_standalone_workspace_manager_uses_the_bounded_cli_backend(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repo = tmp_path / "repo"
        await _repository(repo)
        manager = create_coding_git_workspace_manager(
            cwd=repo,
            state_root=tmp_path / "state",
            managed_root=tmp_path / "checkouts",
            uuid_factory=lambda: "standalone",
        )

        record = await manager.acquire(owner_ref="/root/worker#1")
        (Path(record.path) / "README.md").write_text(
            "standalone\n",
            encoding="utf-8",
        )
        capture = await manager.capture(record.workspace_ref)
        released = await manager.release(record.workspace_ref)

        assert capture.changed is True
        assert released.runtime_owned is False
        assert released.status == "retained"

    asyncio.run(scenario())
