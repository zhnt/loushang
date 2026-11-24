"""Coding compatibility type for authorized workspace operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    ExecutionProfileProvider,
)
from loushang.harness.workspace.operations import (
    ToolOperations,
    WorkspaceOperationAdmission,
)


@dataclass(frozen=True, slots=True)
class CodingWorkspaceOperations(WorkspaceOperationAdmission):
    """Constrain filesystem operations to one admitted Coding workspace."""

    root: Path
    operations: ToolOperations
    execution_profile: EffectiveExecutionProfile
    execution_profile_provider: ExecutionProfileProvider | None = None
    _profile_type_error = "Coding workspace operations require an EffectiveExecutionProfile"


__all__ = ["CodingWorkspaceOperations"]
