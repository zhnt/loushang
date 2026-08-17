"""Frozen authority delegated to one technical child incarnation."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.authorization import EffectiveExecutionProfile

from .types import AgentRef


@dataclass(frozen=True, slots=True)
class DelegatedExecutionProfile:
    """The non-widening authority snapshot consumed by one child session."""

    actor_ref: AgentRef
    allowed_tools: tuple[str, ...]
    execution_profile_ceiling: EffectiveExecutionProfile
    approval_actor_id: str
    workspace_ref: str | None = None

    def __post_init__(self) -> None:
        tools = tuple(self.allowed_tools)
        if any(not isinstance(tool, str) or not tool for tool in tools):
            raise ValueError("allowed_tools must contain non-empty strings")
        if len(set(tools)) != len(tools):
            raise ValueError("allowed_tools must not contain duplicates")
        object.__setattr__(self, "allowed_tools", tools)
        if not isinstance(self.execution_profile_ceiling, EffectiveExecutionProfile):
            raise TypeError(
                "execution_profile_ceiling must be an EffectiveExecutionProfile"
            )
        if self.approval_actor_id != str(self.actor_ref):
            raise ValueError("approval_actor_id must match the child actor incarnation")
        if self.workspace_ref is not None and not self.workspace_ref.strip():
            raise ValueError("workspace_ref must be non-empty when provided")


__all__ = ["DelegatedExecutionProfile"]
