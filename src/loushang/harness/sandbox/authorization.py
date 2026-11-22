from __future__ import annotations

from pathlib import Path

from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    ExecutionProfileProvider,
    constrain_execution_profile,
    select_execution_profile,
)
from loushang.harness.authorization.execution_profile import execution_path_is_covered
from loushang.harness.workspace.exec import ExecRequest

from .types import SandboxScopeRequest


def sandbox_scope_request_from_profile(
    profile: EffectiveExecutionProfile,
    *,
    cwd: str | Path,
) -> SandboxScopeRequest:
    """Project authorized execution authority into an enforcing sandbox scope."""

    return SandboxScopeRequest(
        cwd=Path(cwd),
        readable_roots=profile.readable_roots,
        writable_roots=profile.writable_roots,
        denied_roots=profile.denied_roots,
        network=profile.network,
    )


def authorize_workspace_sandbox_scope(
    request: ExecRequest,
    *,
    workspace_root: Path,
    execution_profile: EffectiveExecutionProfile | None,
    execution_profile_provider: ExecutionProfileProvider | None,
    product_label: str,
) -> SandboxScopeRequest:
    """Select current execution authority and project the requested process scope."""
    if request.cwd is None:
        raise ValueError(f"{product_label} sandbox requires a materialized working directory")
    cwd = Path(request.cwd).expanduser().resolve(strict=False)
    assert execution_profile is not None
    selected = select_execution_profile(execution_profile, execution_profile_provider)
    if (
        not execution_path_is_covered(cwd, selected.readable_roots)
        or execution_path_is_covered(cwd, selected.denied_roots)
        or (execution_profile_provider is None and not cwd.is_relative_to(workspace_root))
    ):
        raise PermissionError(
            f"process cwd is outside the {product_label} sandbox workspace: {cwd}"
        )
    requested_profile = request.execution_profile
    if requested_profile is not None and not isinstance(
        requested_profile, EffectiveExecutionProfile
    ):
        raise TypeError("execution profile must be an EffectiveExecutionProfile")
    return sandbox_scope_request_from_profile(
        constrain_execution_profile(selected, requested_profile or selected), cwd=cwd
    )


__all__ = ["sandbox_scope_request_from_profile"]
