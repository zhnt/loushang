"""Opaque workspace leases carried by the technical multi-agent runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from .types import AgentRef, require_agent_name

WorkspaceMode = Literal["inherit", "isolated"]


@dataclass(frozen=True, slots=True)
class WorkspaceLeaseRequest:
    """Product-neutral request derived from an admitted agent type."""

    agent_ref: AgentRef
    agent_type: str
    mode: WorkspaceMode

    def __post_init__(self) -> None:
        require_agent_name(self.agent_type, field_name="agent type")
        if self.mode not in {"inherit", "isolated"}:
            raise ValueError(f"invalid workspace mode: {self.mode}")


@dataclass(frozen=True, slots=True)
class WorkspaceLease:
    """Opaque identity plus a Product-interpreted execution reference."""

    workspace_ref: str
    execution_ref: str

    def __post_init__(self) -> None:
        if not self.workspace_ref.strip():
            raise ValueError("workspace_ref must be non-empty")
        if not self.execution_ref.strip():
            raise ValueError("workspace execution_ref must be non-empty")


@dataclass(frozen=True, slots=True)
class WorkspaceLeaseSnapshot:
    """Current Product observation without interpreting its change format."""

    workspace_ref: str | None
    artifact_refs: tuple[str, ...] = ()
    change_set_ref: str | None = None
    changed: bool = False
    retained: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))
        if type(self.changed) is not bool or type(self.retained) is not bool:
            raise TypeError("workspace changed and retained flags must be bools")
        if self.workspace_ref is not None and not self.workspace_ref.strip():
            raise ValueError("workspace_ref must be non-empty when provided")
        if any(not ref.strip() for ref in self.artifact_refs):
            raise ValueError("artifact_refs must contain non-empty values")
        if self.change_set_ref is not None and not self.change_set_ref.strip():
            raise ValueError("change_set_ref must be non-empty when provided")
        if self.retained and not self.changed:
            raise ValueError("an unchanged workspace cannot be retained")
        if self.changed and self.workspace_ref is None:
            raise ValueError("a changed workspace must keep a workspace_ref")
        if self.artifact_refs and self.workspace_ref is None:
            raise ValueError("workspace artifacts require a workspace_ref")


class WorkspaceLeasePort(Protocol):
    """Product implementation for acquire, inspect, and release."""

    async def acquire(self, request: WorkspaceLeaseRequest) -> WorkspaceLease: ...

    async def snapshot(self, lease: WorkspaceLease) -> WorkspaceLeaseSnapshot: ...

    async def release(self, lease: WorkspaceLease) -> WorkspaceLeaseSnapshot: ...


__all__ = [
    "WorkspaceLease",
    "WorkspaceLeasePort",
    "WorkspaceLeaseRequest",
    "WorkspaceLeaseSnapshot",
    "WorkspaceMode",
]
