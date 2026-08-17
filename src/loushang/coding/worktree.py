"""Coding adapter for persistent Harness Git workspace handoff."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from loushang.harness.multiagent import (
    WorkspaceLease,
    WorkspaceLeasePort,
    WorkspaceLeaseRequest,
    WorkspaceLeaseSnapshot,
)
from loushang.harness.workspace.exec import ExecService
from loushang.harness.workspace.git_handoff import (
    GitWorkspaceManager,
    GitWorkspaceRecord,
)

_UuidFactory = Callable[[], str]


def default_coding_workspace_state_root() -> Path:
    """Return Coding's durable Product state root outside project worktrees."""

    configured = os.environ.get("XDG_STATE_HOME")
    base = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".local" / "state"
    )
    return (base / "loushang" / "coding" / "git-workspaces").resolve()


def create_coding_git_workspace_manager(
    *,
    cwd: str | Path,
    exec_service: ExecService | None = None,
    state_root: str | Path | None = None,
    managed_root: str | Path | None = None,
    uuid_factory: _UuidFactory | None = None,
    timeout_seconds: float = 60.0,
) -> GitWorkspaceManager:
    root = (
        Path(state_root).expanduser().resolve()
        if state_root is not None
        else default_coding_workspace_state_root()
    )
    checkouts = (
        Path(managed_root).expanduser().resolve()
        if managed_root is not None
        else root / "checkouts"
    )
    return GitWorkspaceManager(
        cwd=cwd,
        state_root=root,
        managed_root=checkouts,
        exec_service=exec_service,
        uuid_factory=uuid_factory,
        timeout_seconds=timeout_seconds,
    )


class CodingGitWorktreeLeasePort(WorkspaceLeasePort):
    """Translate admitted Coding leases into Product-neutral Git mechanics."""

    def __init__(
        self,
        *,
        cwd: str | Path,
        exec_service: ExecService | None = None,
        lease_root: str | Path | None = None,
        state_root: str | Path | None = None,
        uuid_factory: _UuidFactory | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        resolved_cwd = Path(cwd).expanduser().resolve()
        if not resolved_cwd.is_dir():
            raise NotADirectoryError(20, "Not a directory", str(resolved_cwd))
        if timeout_seconds <= 0:
            raise ValueError("worktree timeout_seconds must be positive")
        self._cwd = resolved_cwd
        self._exec = exec_service
        self._state_root = state_root
        self._managed_root = lease_root
        self._uuid_factory = uuid_factory or (lambda: uuid4().hex[:12])
        self._timeout_seconds = timeout_seconds
        self._manager_instance: GitWorkspaceManager | None = None

    @property
    def manager(self) -> GitWorkspaceManager:
        if self._manager_instance is None:
            self._manager_instance = create_coding_git_workspace_manager(
                cwd=self._cwd,
                exec_service=self._exec,
                state_root=self._state_root,
                managed_root=self._managed_root,
                uuid_factory=self._uuid_factory,
                timeout_seconds=self._timeout_seconds,
            )
        return self._manager_instance

    async def acquire(self, request: WorkspaceLeaseRequest) -> WorkspaceLease:
        if request.mode != "isolated":
            raise ValueError("Coding worktree leases require isolated mode")
        record = await self.manager.acquire(
            owner_ref=str(request.agent_ref),
            name_hint="-".join(request.agent_ref.path.parts),
        )
        return WorkspaceLease(
            workspace_ref=record.workspace_ref,
            execution_ref=record.path,
        )

    async def snapshot(self, lease: WorkspaceLease) -> WorkspaceLeaseSnapshot:
        self._require_execution_ref(lease)
        capture = await self.manager.capture(lease.workspace_ref)
        return WorkspaceLeaseSnapshot(
            workspace_ref=capture.record.workspace_ref,
            artifact_refs=capture.artifact_refs,
            changed=capture.changed,
            retained=capture.changed,
        )

    async def release(self, lease: WorkspaceLease) -> WorkspaceLeaseSnapshot:
        self._require_execution_ref(lease)
        record = await self.manager.release(lease.workspace_ref)
        if record.status == "discarded":
            return WorkspaceLeaseSnapshot(workspace_ref=None)
        changed = record.status in {
            "retained",
            "applied",
            "needs_inspection",
            "missing",
        }
        return WorkspaceLeaseSnapshot(
            workspace_ref=record.workspace_ref,
            artifact_refs=record.artifact_refs,
            changed=changed,
            retained=changed,
        )

    def _require_execution_ref(self, lease: WorkspaceLease) -> GitWorkspaceRecord:
        record = self.manager.get(lease.workspace_ref)
        if Path(record.path).resolve() != Path(lease.execution_ref).resolve():
            raise RuntimeError(
                f"workspace execution reference changed: {lease.workspace_ref}"
            )
        return record


__all__ = [
    "CodingGitWorktreeLeasePort",
    "create_coding_git_workspace_manager",
    "default_coding_workspace_state_root",
]
